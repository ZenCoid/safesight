def is_point_in_polygon(px, py, polygon):
    n = len(polygon)
    inside = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i+1) % n]
        if ((y1 > py) != (y2 > py)) and (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1):
            inside = not inside
    return inside

def is_bottom_center_in_zone(bc_x, bc_y, zone_points):
    return is_point_in_polygon(bc_x, bc_y, zone_points)