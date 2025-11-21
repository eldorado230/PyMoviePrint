import sys
import os

try:
    import movieprint_gui
    print("Successfully imported movieprint_gui")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)
except SyntaxError as e:
    print(f"Syntax error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"An error occurred: {e}")
    sys.exit(1)
