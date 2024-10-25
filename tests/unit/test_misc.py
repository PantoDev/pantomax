from panto.utils.misc import is_file_include


def test_is_file_include():
  exclude_patterns = ["*.png", "*.jpg"]
  assert is_file_include("example.txt", exclude_patterns) == True
  assert is_file_include("/hello/example.txt", exclude_patterns) == True
  assert is_file_include("/hello/example.txt", exclude_patterns, default_value=False) == False

def test_is_file_include_exclude_pattern():
  exclude_patterns = ["*.png", "*.jpg", "*.txt"]
  assert is_file_include("example.png", exclude_patterns) == False
  assert is_file_include("/hello/example.jpg", exclude_patterns) == False
  assert is_file_include("/hello/example.txt", exclude_patterns) == False


def test_is_file_include_include_pattern():
  filename = "example.png"
  exclude_patterns = ["!*.png", "*.jpg", "*.txt"]
  assert is_file_include(filename, exclude_patterns) == True


def test_is_file_include_mixed_patterns():
  exclude_patterns = ["*.png", "!example.png", "*.txt"]
  assert is_file_include("example.png", exclude_patterns) == True
  exclude_patterns = ["*.png", "!example.png"]
  assert is_file_include("example.png", exclude_patterns) == True


def test_is_file_include_mixed_patterns2():
  exclude_patterns = ["!example.png", "*.png", "*.txt"]
  assert is_file_include( "example.png", exclude_patterns) == False
  exclude_patterns = ["!example.png", "*.png"]
  assert is_file_include( "example.png", exclude_patterns) == False


def test_is_file_include_no_patterns():
  filename = "example.txt"
  assert is_file_include(filename, []) == True
  assert is_file_include(filename, [], False) == False
