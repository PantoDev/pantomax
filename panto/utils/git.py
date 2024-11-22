import difflib
import enum
import os
import re
import subprocess
import tempfile

from pydantic import BaseModel

from panto.data_models.git import GitPatchFile, GitPatchStatus


class LineContent(BaseModel):
  line_number: int
  content: str


class ChangeOperation(str, enum.Enum):
  ADD = 'ADD'
  DELETE = 'DELETE'
  NOCHANGE = 'NOCHANGE'


class ChangeSet(BaseModel):
  line_content: LineContent
  line_content2: LineContent | None = None
  operation: ChangeOperation


class Hunk(BaseModel):
  old_lines: list[LineContent]
  new_lines: list[LineContent]
  changeset: list[ChangeSet]
  allchangeset: list[ChangeSet]
  old_diff_start: int
  old_diff_length: int
  new_diff_start: int
  new_diff_length: int


class ParsedDiff(BaseModel):
  hunks: list[Hunk]
  raw_diff: str


def parse_hunk_diff(hunk_text: str) -> ParsedDiff:
  """
    Parse a unified diff into a list of old files, new files, and change sets.
  """
  hunks: list[Hunk] = []

  hunk_lines = hunk_text.strip().split('\n')
  oldlines: list[LineContent] = []
  newlines: list[LineContent] = []
  changeset: list[ChangeSet] = []
  allchangeset: list[ChangeSet] = []
  old_line_number = 0
  new_line_number = 0
  old_diff_start = 0
  new_diff_start = 0

  for line in hunk_lines:
    if line.startswith('@@'):
      # Save the current hunk if there are changes recorded
      if oldlines or newlines or changeset or allchangeset:
        hunk = Hunk(
          old_lines=oldlines,
          new_lines=newlines,
          changeset=changeset,
          allchangeset=allchangeset,
          old_diff_start=old_diff_start,
          old_diff_length=len(oldlines),
          new_diff_start=new_diff_start,
          new_diff_length=len(newlines),
        )
        hunks.append(hunk)
        oldlines = []
        newlines = []
        changeset = []
        allchangeset = []
      # Parse the line numbers from the diff header
      header_parts = line.split(' ')
      old_line_number = int(header_parts[1].split(',')[0][1:])
      new_line_number = int(header_parts[2].split(',')[0][1:])
      old_diff_start = old_line_number
      new_diff_start = new_line_number
    elif line.startswith('-'):
      # Line removed from the old file
      line_content = LineContent(line_number=old_line_number, content=line[1:])
      oldlines.append(line_content)
      change = ChangeSet(line_content=line_content, operation=ChangeOperation.DELETE)
      changeset.append(change)
      allchangeset.append(change)
      old_line_number += 1
    elif line.startswith('+'):
      # Line added to the new file
      line_content = LineContent(line_number=new_line_number, content=line[1:])
      newlines.append(line_content)
      change = ChangeSet(line_content=line_content, operation=ChangeOperation.ADD)
      changeset.append(change)
      allchangeset.append(change)
      new_line_number += 1
    else:
      # Line unchanged in both files
      old_line_content = LineContent(line_number=old_line_number, content=line[1:])
      new_line_content = LineContent(line_number=new_line_number, content=line[1:])
      change = ChangeSet(
        line_content=old_line_content,
        line_content2=new_line_content,
        operation=ChangeOperation.NOCHANGE,
      )
      oldlines.append(old_line_content)
      newlines.append(new_line_content)
      allchangeset.append(change)
      old_line_number += 1
      new_line_number += 1

  # Add the last hunk if there are changes recorded
  if oldlines or newlines or changeset or allchangeset:
    hunk = Hunk(
      old_lines=oldlines,
      new_lines=newlines,
      changeset=changeset,
      allchangeset=allchangeset,
      old_diff_start=old_diff_start,
      old_diff_length=len(oldlines),
      new_diff_start=new_diff_start,
      new_diff_length=len(newlines),
    )
    hunks.append(hunk)

  return ParsedDiff(hunks=hunks, raw_diff=hunk_text)


def make_diff(new_file_content: str, old_file_content: str, n_lines: int):
  return make_diff_v2(new_file_content, old_file_content, n_lines)


def make_diff_v2(new_file_content: str, old_file_content: str, n_lines: int):
  if n_lines < 0:
    raise ValueError("n_lines must be a non-negative integer")

  with tempfile.NamedTemporaryFile(delete=False) as new_file:
    with tempfile.NamedTemporaryFile(delete=False) as old_file:
      new_file.write(new_file_content.encode())
      old_file.write(old_file_content.encode())
      new_file.close()
      old_file.close()
      try:
        result = subprocess.run(['git', 'diff', '--no-index', old_file.name, new_file.name],
                                text=True,
                                capture_output=True)
        diff_output = result.stdout
        error_output = result.stderr
        if error_output:
          raise ValueError(f"Error running git diff: {error_output}")
      finally:
        os.remove(new_file.name)
        os.remove(old_file.name)

      splitted = diff_output.split('\n')
      started = False
      output = []
      for s in splitted:
        if s.startswith('@@'):
          started = True
        if started:
          if s == "\\ No newline at end of file":
            continue
          output.append(s)

      return '\n'.join(output)


def make_diff_v1(new_file_content: str, old_file_content: str, n_lines: int):
  if n_lines < 0:
    raise ValueError("n_lines must be a non-negative integer")
  old_file_content_lines = old_file_content.split('\n')
  new_file_content_lines = new_file_content.split('\n')

  changes = []
  for txt in difflib.unified_diff(old_file_content_lines,
                                  new_file_content_lines,
                                  lineterm='',
                                  n=n_lines):
    if txt.startswith('---') or txt.startswith('+++'):
      continue
    changes.append(txt)

  return "\n".join(changes)


def make_old_file_content(new_file_content: str, parsed_diff: ParsedDiff):
  new_file_content_lines = new_file_content.split('\n') if new_file_content else []

  sorted_hunks = sorted(parsed_diff.hunks, key=lambda hunk: hunk.new_diff_start)

  old_file_content_lines = []
  line_no_cursor = 1

  for i, hunk in enumerate(sorted_hunks):
    if line_no_cursor < hunk.new_diff_start:
      old_file_content_lines += new_file_content_lines[line_no_cursor - 1:hunk.new_diff_start - 1]
      line_no_cursor = hunk.new_diff_start

    old_file_content_lines += [
      change.line_content.content for change in hunk.allchangeset
      if change.operation != ChangeOperation.ADD
    ]
    line_no_cursor = hunk.new_diff_start + hunk.new_diff_length
    next_hunk = sorted_hunks[i + 1] if i + 1 < len(sorted_hunks) else None
    if not next_hunk and line_no_cursor < len(new_file_content_lines):
      old_file_content_lines += new_file_content_lines[line_no_cursor - 1:]

  return '\n'.join(old_file_content_lines)


def create_diff_from_line(oldfile_content, new_content, start_line, diff_len):
  if diff_len < 0:
    raise ValueError("diff_len must be a non-negative integer")

  if start_line < 1:
    raise ValueError("start_line must be a positive integer")

  oldfile_content = oldfile_content.split('\n')[start_line - 1:start_line - 1 + diff_len]
  new_content = new_content.split('\n')[start_line - 1:start_line - 1 + diff_len]

  changes = []
  # TODO: This is wrong, we have to add the extra line count after the diff generation
  for text in difflib.unified_diff(oldfile_content, new_content, lineterm='', n=diff_len):
    if text.startswith('---') or text.startswith('+++'):
      continue
    changes.append(text)

  return "\n".join(changes)


def parsed_hunk_to_string(hunk: Hunk, add_header=True, add_lineno=True) -> str:
  diff_content = ""
  if add_header:
    diff_content += f"\t\t@@ -{hunk.old_diff_start},{hunk.old_diff_length} +{hunk.new_diff_start},{hunk.new_diff_length} @@\n"  # noqa: E501
  for change in hunk.allchangeset:
    old_line_no: str | int = ""
    new_line_no: str | int = ""
    operation = ""
    line_content = ""

    if change.operation == ChangeOperation.ADD:
      operation = "+"
      old_line_no = ""
      new_line_no = change.line_content.line_number
      line_content = change.line_content.content
    elif change.operation == ChangeOperation.DELETE:
      operation = "-"
      old_line_no = change.line_content.line_number
      new_line_no = ""
      line_content = change.line_content.content
    elif change.operation == ChangeOperation.NOCHANGE:
      operation = " "
      old_line_no = change.line_content.line_number
      new_line_no = change.line_content2.line_number if change.line_content2 else old_line_no
      line_content = change.line_content.content

    if add_lineno:
      diff_content += f"{old_line_no}\t{new_line_no}\t{operation} {line_content}\n"
    else:
      diff_content += f"{operation} {line_content}\n"
  return diff_content


def diff_str_to_patchfiles(diff_str: str) -> list[GitPatchFile]:
  files: list[GitPatchFile] = []
  patch = ""
  for line in diff_str.splitlines():
    if line.startswith('index ') or line.startswith('--- ') or line.startswith(
        '+++ ') or line.startswith('similarity index ') or line.startswith(
          'rename from ') or line.startswith('rename to '):
      continue
    if line.startswith('new file mode'):
      if files:
        files[-1].status = GitPatchStatus.ADDED
      continue
    if line.startswith('deleted file mode'):
      if files:
        files[-1].status = GitPatchStatus.REMOVED
      continue

    if line.startswith('diff --git'):
      if files:
        files[-1].patch = patch
      splitted = line.split(' ')
      if len(splitted) == 4:
        diff_file_1 = splitted[2].replace('a/', '', 1)
        diff_file_2 = splitted[3].replace('b/', '', 1)
      else:
        # This is a special case when file name contains space
        file_pattern = r"diff --git a/(.+?) b/((.+?)+)"
        matches = re.match(file_pattern, line)
        assert matches, f"Failed to match file name from line: {line}"
        diff_file_1 = matches.group(1)
        diff_file_2 = matches.group(2)

      patch = ""
      if diff_file_1 != diff_file_2:
        files.append(
          GitPatchFile(filename=diff_file_2,
                       status=GitPatchStatus.RENAMED,
                       patch=patch,
                       old_filename=diff_file_1))
      else:
        files.append(
          GitPatchFile(filename=diff_file_2, status=GitPatchStatus.MODIFIED, patch=patch))
    else:
      patch += line + "\n"

  if patch and files:
    files[-1].patch = patch

  return files


def gitlab_diff_to_patch_files(gitlab_files: list) -> list[GitPatchFile]:
  patch_files = []
  for file in gitlab_files:
    status = GitPatchStatus.MODIFIED
    if file['deleted_file']:
      status = GitPatchStatus.REMOVED
    if file['new_file']:
      status = GitPatchStatus.ADDED
    if file['renamed_file']:
      status = GitPatchStatus.RENAMED
    diff = file['diff'] or ''
    filename = file['new_path']
    patchfile = GitPatchFile(
      filename=filename,
      status=status,
      patch=diff,
      old_filename=file['old_path'],
    )
    patch_files.append(patchfile)
  return patch_files


def drop_empty_patches(patches: list[GitPatchFile]) -> list[GitPatchFile]:
  new_patches: list[GitPatchFile] = []
  for p in patches:
    diff = parse_hunk_diff(p.patch)
    for h in diff.hunks:
      if any(c.line_content.content.strip() for c in h.changeset):
        new_patches.append(p)
        break
  return new_patches


def omit_no_endlines_from_patch(patchtxt: str) -> str:
  lines = patchtxt.split('\n')
  new_lines = []
  for line in lines:
    if line == "\\ No newline at end of file":
      continue
    new_lines.append(line)
  return '\n'.join(new_lines)
