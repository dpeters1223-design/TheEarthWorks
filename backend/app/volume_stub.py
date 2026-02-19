def polygon_area(points):
    area = 0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]["x"], points[i]["y"]
        x2, y2 = points[(i + 1) % n]["x"], points[(i + 1) % n]["y"]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2

def compute_cut_fill_stub(points, ft_per_pixel=0.2, assumed_depth_ft=2.0):
    area_px2 = polygon_area(points)
    area_ft2 = area_px2 * (ft_per_pixel ** 2)
    volume_ft3 = area_ft2 * assumed_depth_ft
    volume_cy = volume_ft3 / 27.0

    return {
        "area_ft2": area_ft2,
        "volume_cy_estimate": volume_cy
    }
