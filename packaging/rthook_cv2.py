"""Runtime hook: let OpenCV find its compiled half inside a Mac app bundle.

cv2's loader adds its own folder to sys.path and imports "cv2" again, expecting
the compiled file. It puts that folder first only when sys.path[0] is the parent
of the folder. In a Mac bundle it is not: sys.path[0] is Contents/Frameworks and
the loader's real folder is Contents/Resources/cv2. So it found itself instead:
"recursion is detected during loading of cv2 binary extensions", and RapidOCR was
unusable on every Mac build (first real run of the check: CI run 45609774726).

OpenCV_REPLACE_SYS_PATH_0 is the loader's own switch for "put it first".
"""
import sys

if sys.platform == "darwin":
    sys.OpenCV_REPLACE_SYS_PATH_0 = True
