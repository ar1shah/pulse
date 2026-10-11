"""Display filter for the x of one LD2450 track: outlier gate, median, EMA, deadband.

Only x: the LD2450's left/right comes from a 2-antenna phase angle and is noisy, its range (y) is clean.
Fusion keeps one XFilter per track. Association still runs on the raw detections (fusion.py), so a lagging
display never costs a match; only the x that reaches the screen (and the lock cone) goes through here.
All the knobs are the constants below. Too jumpy: raise MEDIAN_N or DEADBAND_X_MM, lower EMA_ALPHA.
Too laggy: the reverse. Phantom dots: raise CONFIRM_FRAMES.
"""
import math
from collections import deque
from statistics import median

OUTLIER_X_MM = 1000     # an x more than this from the recent median is ignored (counts as a miss) ...
OUTLIER_RESET = 3       # ... unless it happens this many frames in a row: the person really is there, restart
MEDIAN_N = 5            # samples in the median window. Bigger = steadier, laggier (lag ~ N/2 frames)
EMA_ALPHA = 0.35        # weight of the newest median in the EMA. Smaller = smoother, laggier
DEADBAND_X_MM = 80      # the shown x only moves once the filtered x is this far from it (stops the shiver,
                        # and a reversal shorter than 2x this never shows: no more wrong-way steps)
VEL_CLIP_MM = 250       # (fusion.py) a residual is clipped to this before it feeds the velocity: one far return
                        # used to kick it ~750 mm/s, often the wrong way, and the track lost its person
CONFIRM_FRAMES = 3      # (fusion.py) detections before a new track is shown; kills short-lived ghosts
TENTATIVE_DROP_S = 0.3  # an unconfirmed track missing this long is dropped, not held


def _deadband(shown: float, target: float, band: float) -> float:
    """Follow target, but stay put while it is within band; when it leaves, trail it at exactly band."""
    d = target - shown
    if abs(d) <= band:
        return shown
    return target - math.copysign(band, d)


class XFilter:
    def __init__(self, x: float) -> None:
        self._xs: deque[float] = deque([x], maxlen=MEDIAN_N)
        self._ema = x
        self.x = x                      # what the screen shows
        self._outliers = 0

    def update(self, x: float) -> bool:
        """Feed one detection's x. False if it was rejected as an outlier (the caller counts it as a miss)."""
        if abs(x - median(self._xs)) > OUTLIER_X_MM:
            self._outliers += 1
            if self._outliers < OUTLIER_RESET:
                return False
            self.__init__(x)
            return True
        self._outliers = 0
        self._xs.append(x)
        self._ema += EMA_ALPHA * (median(self._xs) - self._ema)
        self.x = _deadband(self.x, self._ema, DEADBAND_X_MM)
        return True
