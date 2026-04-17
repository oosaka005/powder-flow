import os
import math

import cv2
import numpy as np
from sklearn.linear_model import LinearRegression, RANSACRegressor


REPOSE_ARTIFACT_CROPPED = "repose_cropped_image"
REPOSE_ARTIFACT_PROCESSED = "repose_processed_image"
REPOSE_ARTIFACT_FIT = "repose_fit_image"


def load_image(image_path):
    arr = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise ValueError(f"Failed to load image: {image_path}")
    return arr


def _largest_contour(binary):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _find_powder_contour(binary):
    h, w = binary.shape[:2]
    area_limit = 0.9 * h * w
    contour = _largest_contour(binary)
    if contour is None:
        return None

    # If thresholding flips to a white background, invert and re-detect.
    if cv2.contourArea(contour) > area_limit:
        inverted = cv2.bitwise_not(binary)
        contour = _largest_contour(inverted)

    return contour


def _preprocess_repose(
    arr,
    crop_top_ratio=0.3,
    crop_bottom_ratio=0.05,
    crop_left_ratio=0.2,
    crop_right_ratio=0.2,
    morph_kernel_size=20,
    morph_iter=5,
    binary_threshold=190,
):
    height = arr.shape[0]
    width = arr.shape[1]
    top = int(height * crop_top_ratio)
    bottom = int(height * (1.0 - crop_bottom_ratio))
    left = int(width * crop_left_ratio)
    right = int(width * (1.0 - crop_right_ratio))
    cropped = arr[top:bottom, left:right]

    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(
        blurred, binary_threshold, 255, cv2.THRESH_BINARY
    )
    contour = _find_powder_contour(binary)
    if contour is None:
        binary_selected = binary
    else:
        binary_selected = cv2.drawContours(
            np.zeros_like(binary), [contour], -1, 255, thickness=cv2.FILLED
        )
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size)
    )
    binary_morph = cv2.morphologyEx(
        binary_selected, cv2.MORPH_CLOSE, kernel, iterations=morph_iter
    )
    binary_morph = cv2.morphologyEx(
        binary_morph, cv2.MORPH_OPEN, kernel, iterations=morph_iter
    )
    return cropped, binary, binary_morph


def _direct_profile_upper_envelope_from_contour(contour, width):
    """
    For each x, take the topmost y from the contour points.
    For stricter behavior, switch to a mask-based top_y extraction.
    """
    envelope_y = np.full(width, np.inf, dtype=np.float32)
    points = contour.reshape(-1, 2)
    for x, y in points:
        if 0 <= x < width and y < envelope_y[x]:
            envelope_y[x] = y

    xs = np.where(np.isfinite(envelope_y))[0]
    ys = envelope_y[xs]
    return xs.astype(np.float32), ys.astype(np.float32)


def _direct_profile_fit_angle_ransac(xs, ys):
    if xs.size < 2:
        return None

    x = xs.reshape(-1, 1).astype(np.float32)
    y = ys.reshape(-1, 1).astype(np.float32)

    min_samples = max(2, int(0.2 * len(x)))
    min_samples = min(min_samples, len(x))
    model = RANSACRegressor(
        estimator=LinearRegression(),
        min_samples=min_samples,
        residual_threshold=2.0,
        random_state=0,
    )
    model.fit(x, y)
    slope = float(model.estimator_.coef_[0][0])
    intercept = float(model.estimator_.intercept_[0])
    angle = math.degrees(math.atan(abs(slope)))
    return angle, slope, intercept


def _select_direct_profile_stable_angle(
    x,
    y,
    base_percentile,
    n_bins,
    k_keep,
    expected_slope_sign,
):
    if x.size == 0:
        return None

    y_apex = float(np.min(y))
    y_base = float(np.percentile(y, base_percentile))
    H = y_base - y_apex
    if H <= 1e-6:
        return None

    idx = ((y - y_apex) / H * n_bins).astype(np.int32)
    idx = np.clip(idx, 0, n_bins - 1)

    angles = [None] * n_bins
    bin_fits = [None] * n_bins
    bin_points = []
    for i in range(n_bins):
        sel = idx == i
        x_bin = x[sel]
        y_bin = y[sel]
        bin_points.append((x_bin, y_bin))
        fit = _direct_profile_fit_angle_ransac(x_bin, y_bin)
        if fit is not None:
            angles[i] = float(fit[0])
            bin_fits[i] = fit

    # Drop bins with the wrong slope direction.
    for i, fit in enumerate(bin_fits):
        if fit is None:
            continue
        _, slope, _ = fit
        if slope == 0:
            angles[i] = None
            bin_fits[i] = None
            continue
        sign = 1 if slope > 0 else -1
        if sign != expected_slope_sign:
            angles[i] = None
            bin_fits[i] = None

    # Always exclude the two topmost and two bottommost bins.
    for i in (0, 1, n_bins - 2, n_bins - 1):
        angles[i] = None
        bin_fits[i] = None

    selected_bins_all = [i for i, a in enumerate(angles) if a is not None]
    if len(selected_bins_all) < k_keep:
        return None
    selected_bins = selected_bins_all[:k_keep]
    sel_x = np.concatenate([bin_points[i][0] for i in selected_bins])
    sel_y = np.concatenate([bin_points[i][1] for i in selected_bins])
    sel_fit = _direct_profile_fit_angle_ransac(sel_x, sel_y) if sel_x.size >= 2 else None
    mean_angle = float(np.mean([angles[i] for i in selected_bins]))
    return (
        mean_angle,
        sel_fit,
        sel_x,
        sel_y,
        selected_bins,
        bin_fits,
        bin_points,
    )


def _analyze_direct_profile_angle(
    cropped,
    binary,
    base_percentile=95,
    n_bins=8,
    k_keep=4,
):
    contour = _find_powder_contour(binary)
    if contour is None:
        raise RuntimeError("No contour found in binary image.")

    xs, ys = _direct_profile_upper_envelope_from_contour(contour, binary.shape[1])
    if xs.size < 10:
        raise RuntimeError("Upper envelope points too few.")

    peak_idx = int(np.argmin(ys))
    peak_x = xs[peak_idx]

    left_mask = xs < peak_x
    right_mask = xs > peak_x

    left_x = xs[left_mask]
    left_y = ys[left_mask]
    right_x = xs[right_mask]
    right_y = ys[right_mask]

    left_result = _select_direct_profile_stable_angle(
        left_x,
        left_y,
        base_percentile,
        n_bins,
        k_keep,
        expected_slope_sign=-1,
    )
    right_result = _select_direct_profile_stable_angle(
        right_x,
        right_y,
        base_percentile,
        n_bins,
        k_keep,
        expected_slope_sign=1,
    )
    if left_result is None or right_result is None:
        raise RuntimeError("Failed to select stable bins for both sides.")

    (
        left_angle,
        left_fit,
        left_sel_x,
        left_sel_y,
        left_bins,
        left_bin_fits,
        left_bin_points,
    ) = left_result
    (
        right_angle,
        right_fit,
        right_sel_x,
        right_sel_y,
        right_bins,
        right_bin_fits,
        right_bin_points,
    ) = right_result
    mean_angle = (left_angle + right_angle) / 2.0

    overlay = cropped.copy()
    contour_overlay = cropped.copy()

    def _draw_bin_fits(img, bin_fits, bin_points, selected_bins, color):
        selected = set(selected_bins)
        for i, fit in enumerate(bin_fits):
            if fit is None:
                continue
            x_bin, _ = bin_points[i]
            if x_bin.size < 2:
                continue
            _, slope, intercept = fit
            x1 = int(np.min(x_bin))
            x2 = int(np.max(x_bin))
            y1 = int(slope * x1 + intercept)
            y2 = int(slope * x2 + intercept)
            thickness = 5 if i in selected else 1
            cv2.line(img, (x1, y1), (x2, y2), color, thickness)

    _draw_bin_fits(overlay, left_bin_fits, left_bin_points, left_bins, (0, 0, 255))
    _draw_bin_fits(overlay, right_bin_fits, right_bin_points, right_bins, (0, 255, 0))

    for fit_x, fit_y, color in (
        (left_sel_x, left_sel_y, (0, 0, 255)),
        (right_sel_x, right_sel_y, (0, 255, 0)),
    ):
        if fit_x.size == 0:
            continue
        for x, y in zip(fit_x, fit_y):
            cv2.circle(contour_overlay, (int(x), int(y)), 2, color, -1)

    for fit, fit_x, color in (
        (left_fit, left_sel_x, (0, 0, 255)),
        (right_fit, right_sel_x, (0, 255, 0)),
    ):
        if fit is None or fit_x.size < 2:
            continue
        _, slope, intercept = fit
        x1 = int(np.min(fit_x))
        x2 = int(np.max(fit_x))
        y1 = int(slope * x1 + intercept)
        y2 = int(slope * x2 + intercept)
        cv2.line(overlay, (x1, y1), (x2, y2), color, 4)

    return overlay, contour_overlay, left_angle, right_angle, mean_angle


def _find_shoulder_point(xs, ys, side, slope_threshold, window=30):
    """
    Find the shoulder point where the gentle repose slope transitions to the
    near-vertical wall drop.  Scans outward from the apex so that background
    floor regions on either side do not cause false early returns.

    For 'left':  xs is sorted ascending, xs[n-1] = apex, xs[0] = leftmost.
    For 'right': xs is sorted ascending, xs[0]   = apex, xs[n-1] = rightmost.

    Returns (x, y) of the shoulder (last gentle-slope point before steep drop).
    """
    n = len(xs)
    if n <= window:
        raise RuntimeError(
            f"{side.capitalize()} shoulder not detected: not enough envelope points."
        )

    if side == "left":
        # Scan from apex (index n-1) leftward toward index 0.
        for i in range(n - 1, window - 1, -1):
            dx = float(xs[i] - xs[i - window])
            dy = float(ys[i] - ys[i - window])
            if dx > 0 and abs(dy / dx) >= slope_threshold:
                # xs[i] is the apex-side boundary of the first steep window found.
                return float(xs[i]), float(ys[i])
        # No steep wall drop found: pile ends naturally at the leftmost point.
        return float(xs[0]), float(ys[0])
    else:
        # Scan from apex (index 0) rightward toward index n-1.
        for i in range(n - window):
            dx = float(xs[i + window] - xs[i])
            dy = float(ys[i + window] - ys[i])
            if dx > 0 and abs(dy / dx) >= slope_threshold:
                # xs[i] is the apex-side boundary of the first steep window found.
                return float(xs[i]), float(ys[i])
        # No steep wall drop found: pile ends naturally at the rightmost point.
        return float(xs[-1]), float(ys[-1])


def _analyze_shoulder_baseline_angle(
    cropped,
    binary,
    slope_threshold_deg=70,
    window=30,
):
    """
    Estimate the angle of repose using the shoulder-baseline method.

    1. Detect upper envelope of the powder contour.
    2. On each side, find the shoulder: the outermost point where the slope
       transitions from the near-vertical wall-drop to the gradual pile surface.
    3. Draw a horizontal baseline at the height of the higher (lower y) shoulder.
    4. angle = atan(pile_height / half_base_width)
    """
    contour = _find_powder_contour(binary)
    if contour is None:
        raise RuntimeError("No contour found in binary image.")

    width = binary.shape[1]
    xs, ys = _direct_profile_upper_envelope_from_contour(contour, width)
    if xs.size < 10:
        raise RuntimeError("Upper envelope points too few.")

    sort_idx = np.argsort(xs)
    xs = xs[sort_idx]
    ys = ys[sort_idx]

    # Apex: centroid x of all points within 2% of the pile height above the minimum y.
    min_y = float(np.min(ys))
    max_y = float(np.max(ys))
    top_margin = max(5.0, (max_y - min_y) * 0.02)
    top_mask = ys <= min_y + top_margin
    apex_x = float(np.median(xs[top_mask]))
    apex_y = min_y
    apex_idx = int(np.argmin(np.abs(xs - apex_x)))

    left_xs = xs[: apex_idx + 1]
    left_ys = ys[: apex_idx + 1]
    right_xs = xs[apex_idx :]
    right_ys = ys[apex_idx :]

    slope_threshold = math.tan(math.radians(slope_threshold_deg))

    left_sx, left_sy = _find_shoulder_point(left_xs, left_ys, "left", slope_threshold, window)
    right_sx, right_sy = _find_shoulder_point(right_xs, right_ys, "right", slope_threshold, window)

    baseline_y = float(min(left_sy, right_sy))
    base = float(right_sx - left_sx)
    if base <= 0:
        raise RuntimeError("Shoulder detection failed: shoulders are inverted.")

    height = baseline_y - apex_y
    if height <= 0:
        raise RuntimeError("Shoulder detection failed: apex is at or below baseline.")

    mean_angle = math.degrees(math.atan(height / (base / 2.0)))

    overlay = cropped.copy()

    # Baseline (blue)
    cv2.line(overlay, (int(left_sx), int(baseline_y)), (int(right_sx), int(baseline_y)), (255, 0, 0), 3)
    # Vertical height line from apex to baseline (green)
    cv2.line(overlay, (int(apex_x), int(apex_y)), (int(apex_x), int(baseline_y)), (0, 255, 0), 3)
    # Left slope line (red)
    cv2.line(overlay, (int(left_sx), int(baseline_y)), (int(apex_x), int(apex_y)), (0, 0, 255), 3)
    # Right slope line (cyan)
    cv2.line(overlay, (int(right_sx), int(baseline_y)), (int(apex_x), int(apex_y)), (0, 255, 255), 3)

    # Shoulder and apex markers
    cv2.circle(overlay, (int(left_sx), int(left_sy)), 14, (0, 0, 255), -1)
    cv2.circle(overlay, (int(right_sx), int(right_sy)), 14, (0, 255, 255), -1)
    cv2.circle(overlay, (int(apex_x), int(apex_y)), 14, (255, 0, 0), -1)

    cv2.putText(overlay, f"Angle: {mean_angle:.2f} deg",
                (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4, cv2.LINE_AA)
    cv2.putText(overlay, f"Base: {base:.0f}px  Height: {height:.0f}px",
                (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(
        overlay,
        f"L({int(left_sx)},{int(left_sy)})  R({int(right_sx)},{int(right_sy)})  Apex({int(apex_x)},{int(apex_y)})",
        (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA,
    )

    return overlay, mean_angle


def analyze_repose(image_path, output_dir=None, file_prefix="", method="direct_profile"):
    """
    Analyze a powder image and return (artifacts, angle_deg).
    If output_dir is provided, save the generated images there as well.

    method:
        "direct_profile"    - original RANSAC-based slope fitting (default)
        "shoulder_baseline" - USP geometric method (height / half-base)
    """
    arr = load_image(image_path)
    artifacts: dict[str, np.ndarray] = {}

    cropped, binary, binary_smooth = _preprocess_repose(arr)
    artifacts[REPOSE_ARTIFACT_CROPPED] = cropped
    artifacts[REPOSE_ARTIFACT_PROCESSED] = binary_smooth

    # Save preprocessing artifacts immediately so they are available even if analysis fails.
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        for key in (REPOSE_ARTIFACT_CROPPED, REPOSE_ARTIFACT_PROCESSED):
            file_stub = key.replace("repose_", "").replace("_image", "")
            cv2.imwrite(os.path.join(output_dir, f"{file_prefix}{file_stub}.png"), artifacts[key])

    if method == "shoulder_baseline":
        overlay, mean_angle = _analyze_shoulder_baseline_angle(cropped, binary_smooth)
        artifacts[REPOSE_ARTIFACT_FIT] = overlay
    else:
        overlay, contour_overlay, _left, _right, mean_angle = _analyze_direct_profile_angle(
            cropped, binary_smooth
        )
        artifacts[REPOSE_ARTIFACT_FIT] = overlay
        artifacts[REPOSE_ARTIFACT_PROCESSED] = contour_overlay

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        for artifact_key, image in artifacts.items():
            file_stub = artifact_key.replace("repose_", "").replace("_image", "")
            cv2.imwrite(os.path.join(output_dir, f"{file_prefix}{file_stub}.png"), image)

    return artifacts, mean_angle


