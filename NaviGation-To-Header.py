import os
import sys
import math
import struct

class NavBuffer:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read_uint32(self):
        if self.pos + 4 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<I', self.data[self.pos:self.pos + 4])[0]
        self.pos += 4
        return value

    def read_int32(self):
        if self.pos + 4 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<i', self.data[self.pos:self.pos + 4])[0]
        self.pos += 4
        return value

    def read_int64(self):
        if self.pos + 8 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<q', self.data[self.pos:self.pos + 8])[0]
        self.pos += 8
        return value

    def read_uint8(self):
        if self.pos + 1 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<B', self.data[self.pos:self.pos + 1])[0]
        self.pos += 1
        return value

    def read_uint16(self):
        if self.pos + 2 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<H', self.data[self.pos:self.pos + 2])[0]
        self.pos += 2
        return value

    def read_float(self):
        if self.pos + 4 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<f', self.data[self.pos:self.pos + 4])[0]
        self.pos += 4
        return value

    def read_vec3(self):
        if self.pos + 12 > len(self.data):
            raise Exception(f"Buffer overflow at pos {self.pos}, size {len(self.data)}")
        value = struct.unpack('<3f', self.data[self.pos:self.pos + 12])
        self.pos += 12
        return value

    def skip(self, n):
        if self.pos + n > len(self.data):
            raise Exception(f"Skip overflow at pos {self.pos}, need {n}, size {len(self.data)}")
        self.pos += n

    def bytes_remaining(self):
        return len(self.data) - self.pos

class NavArea:
    def __init__(self, buffer, file_version, polygons):
        self.start_pos = buffer.pos

        self.id = buffer.read_uint32()
        self.dynamic_attribute_flags = buffer.read_int64()
        self.hull_index = buffer.read_uint8()

        if file_version >= 31:
            polygon_index = buffer.read_uint32()
            if polygon_index < len(polygons):
                self.corners = polygons[polygon_index]
            else:
                raise Exception(f"Polygon index {polygon_index} out of range")
        else:
            corner_count = buffer.read_uint32()
            self.corners = []
            for _ in range(corner_count):
                self.corners.append(buffer.read_vec3())

        buffer.read_float()

        self.connections = []
        for _ in range(len(self.corners)):
            connection_count = buffer.read_uint32()
            edge_connections = []
            for _ in range(connection_count):
                area_id = buffer.read_uint32()
                edge_id = buffer.read_uint32()
                edge_connections.append((area_id, edge_id))
            self.connections.append(edge_connections)

        buffer.read_uint8()
        buffer.read_uint32()

        ladder_above_count = buffer.read_uint32()
        self.ladders_above = []
        for _ in range(ladder_above_count):
            self.ladders_above.append(buffer.read_uint32())

        ladder_below_count = buffer.read_uint32()
        self.ladders_below = []
        for _ in range(ladder_below_count):
            self.ladders_below.append(buffer.read_uint32())

    def center(self):
        if not self.corners:
            return (0, 0, 0)
        cx = sum(c[0] for c in self.corners) / len(self.corners)
        cy = sum(c[1] for c in self.corners) / len(self.corners)
        cz = sum(c[2] for c in self.corners) / len(self.corners)
        return (cx, cy, cz)

    def width(self):
        if not self.corners:
            return 0.0
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        return max(max(xs) - min(xs), max(ys) - min(ys))

class NavFile:
    def __init__(self, filepath):
        with open(filepath, 'rb') as f:
            data = f.read()

        print(f"File size: {len(data)} bytes")
        buffer = NavBuffer(data)

        magic = buffer.read_uint32()
        if magic != 0xFEEDFACE:
            raise Exception(f"Invalid magic: {hex(magic)}")

        self.version = buffer.read_uint32()
        print(f"Version: {self.version}")

        self.sub_version = buffer.read_uint32()
        print(f"Sub version: {self.sub_version}")

        flags = buffer.read_uint32()
        self.is_analyzed = (flags & 0x00000001) != 0

        if self.version >= 36:
            buffer.pos = 145
        elif self.version >= 35:
            buffer.pos = 16
        else:
            raise Exception(f"Unsupported nav version: {self.version}")

        self.polygons = self.read_polygons(buffer)
        print(f"Polygons: {len(self.polygons)}")
        print(f"Position after polygons: {buffer.pos}")

        buffer = self.find_areas_start(buffer)
        area_count = buffer.read_uint32()
        print(f"Area count: {area_count}")

        self.areas = []
        for i in range(area_count):
            try:
                area = NavArea(buffer, self.version, self.polygons)
            except Exception as e:
                raise Exception(
                    f"Failed at area {i}/{area_count} (pos {buffer.pos}): {e}"
                )
            self.areas.append(area)
            if (i + 1) % 500 == 0:
                print(f"  Loaded {i + 1}/{area_count} areas")

        print(f"Done! Total areas: {len(self.areas)}")
        self.build_connections()

    def read_polygons(self, buffer):
        corner_count = buffer.read_uint32()
        print(f"Corner count: {corner_count}")
        corners = []
        for _ in range(corner_count):
            corners.append(buffer.read_vec3())

        polygon_count = buffer.read_uint32()
        print(f"Polygon count: {polygon_count}")
        polygons = []
        for _ in range(polygon_count):
            corner_count_in_poly = buffer.read_uint8()
            polygon = []
            for _ in range(corner_count_in_poly):
                corner_index = buffer.read_uint32()
                if corner_index < len(corners):
                    polygon.append(corners[corner_index])
                else:
                    raise Exception(f"Corner index {corner_index} out of range")

            if self.version >= 35:
                buffer.read_uint32()

            polygons.append(polygon)

        return polygons

    def find_areas_start(self, buffer):
        data = buffer.data
        print("Searching for areas...")

        polys_end = buffer.pos
        n = len(data)
        needle = b'\x01\x00\x00\x00'

        candidates = []

        search_pos = max(polys_end - 4, 0)
        while True:
            idx = data.find(needle, search_pos)
            if idx < 0:
                break
            search_pos = idx + 1

            pos = idx - 4
            if pos < 0 or pos + 21 > n:
                continue

            count = struct.unpack_from('<I', data, pos)[0]
            if count < 500 or count > 15000:
                continue

            flags_val = struct.unpack_from('<q', data, pos + 8)[0]
            if abs(flags_val) > 0x10000000000:
                continue

            hull_idx = data[pos + 16]
            if hull_idx > 10:
                continue

            poly_idx = struct.unpack_from('<I', data, pos + 17)[0]
            if poly_idx >= len(self.polygons):
                continue

            candidates.append((pos, count, hull_idx, poly_idx))

        if not candidates:
            raise Exception("Could not find areas data")

        candidates.sort(key=lambda c: c[1], reverse=True)

        best = None
        best_read = -1

        for pos, count, hull_idx, poly_idx in candidates:
            if count <= best_read:
                continue

            test_buf = NavBuffer(data)
            test_buf.pos = pos + 4
            read = 0
            try:
                for _ in range(count):
                    area = NavArea(test_buf, self.version, self.polygons)
                    if not area.corners:
                        break
                    read += 1
            except Exception:
                pass

            if read > best_read:
                best_read = read
                best = (pos, count, hull_idx, poly_idx)
                if best_read == count:
                    break

        if best is None or best_read < 3:
            raise Exception(f"Could not find valid areas data (best read {best_read})")

        pos, count, hull_idx, poly_idx = best
        buffer.pos = pos
        print(f"Found areas at pos {pos} (read {best_read}/{count} areas)")
        print(f"  area_count: {count}")
        print(f"  first area_id: 1")
        print(f"  hull_index: {hull_idx}")
        print(f"  polygon_index: {poly_idx}")
        return buffer

    def build_connections(self):
        self.connections = {}

        id_to_area = {a.id: a for a in self.areas}

        for area in self.areas:
            neighbors = {}

            for edge_connections in area.connections:
                for area_id, edge_id in edge_connections:
                    if area_id == area.id:
                        continue

                    neighbor = id_to_area.get(area_id)
                    if neighbor is None:
                        continue

                    center1 = area.center()
                    center2 = neighbor.center()

                    dx = center1[0] - center2[0]
                    dy = center1[1] - center2[1]
                    dz = center1[2] - center2[2]

                    if abs(dz) > 150:
                        continue

                    dist_2d = math.sqrt(dx * dx + dy * dy)
                    dist = dist_2d + abs(dz) * 0.3

                    if area_id not in neighbors:
                        neighbors[area_id] = dist

            self.connections[area.id] = list(neighbors.items())

def sanitize_map_name(nav_filename):
    base = os.path.splitext(os.path.basename(nav_filename))[0]
    return base.upper().replace('-', '_').replace(' ', '_')

def generate_header(nav_file, output_path, map_name):
    array_name = f"{map_name}_NAV_DATA"
    count_name = f"{map_name}_NAV_NODE_COUNT"

    valid_areas = [a for a in nav_file.areas if len(nav_file.connections.get(a.id, [])) > 0]
    print(f"Valid areas: {len(valid_areas)}/{len(nav_file.areas)}")

    id_to_index = {area.id: i for i, area in enumerate(valid_areas)}

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("// Auto-generated from CS2 .nav file\n")
        f.write("// Version: {}\n".format(nav_file.version))
        f.write("// Total nodes: {}\n\n".format(len(valid_areas)))
        f.write("#pragma once\n\n")
        f.write('#include "CEmbeddedNavNode.h"\n\n')
        f.write(f"static const CEmbeddedNavNode {array_name}[] = \n{{\n")

        for area in valid_areas:
            neighbors = nav_file.connections[area.id]

            if len(neighbors) > 16:
                neighbors.sort(key=lambda x: x[1])
                neighbors = neighbors[:16]

            neighbor_indices = []
            neighbor_distances = []

            for neighbor_id, dist in neighbors:
                if neighbor_id in id_to_index:
                    neighbor_indices.append(id_to_index[neighbor_id])
                    neighbor_distances.append(dist)

            center = area.center()
            width = area.width()

            f.write("    {\n")
            f.write("        {},\n".format(id_to_index[area.id]))
            f.write("        {:.6f}f,\n".format(width))
            f.write("        {{{:.6f}f, {:.6f}f, {:.6f}f}},\n".format(
                center[0], center[1], center[2]
            ))
            f.write("        {},\n".format(len(neighbor_indices)))
            f.write("        {")
            for i in range(16):
                if i < len(neighbor_indices):
                    f.write("{}".format(neighbor_indices[i]))
                else:
                    f.write("0")
                if i < 15:
                    f.write(", ")
            f.write("},\n")
            f.write("        {")
            for i in range(16):
                if i < len(neighbor_distances):
                    f.write("{:.6f}f".format(neighbor_distances[i]))
                else:
                    f.write("0.0f")
                if i < 15:
                    f.write(", ")
            f.write("},\n")
            f.write("    },\n")

        f.write("};\n\n")
        f.write(f"static const int {count_name} = {len(valid_areas)};\n")

    print(f"Header written to: {output_path}")

def write_embedded_nav_node_header(output_path):
    content = """#pragma once

class CEmbeddedNavNode
{
public:
    int Index;
    float Width;
    Vector3 Position;
    int NeighborCount;
    int NeighborIndices[16];
    float NeighborDistances[16];
};
"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Written: {output_path}")

def print_help():
    print("Usage:")
    print("  python NaviGation-To-Header.py")
    print("  python NaviGation-To-Header.py <nav_dir>")
    print("  python NaviGation-To-Header.py <nav_dir> <header_dir>")
    print("  python NaviGation-To-Header.py <file.nav>")
    print("  python NaviGation-To-Header.py <file.nav> <out.h>")
    print("")
    print("Modes:")
    print("  no args                Batch mode. Use <script_dir>/output -> <script_dir>/output_header")
    print("  <nav_dir>              Batch mode. Use <nav_dir> -> <script_dir>/output_header")
    print("  <nav_dir> <header_dir> Batch mode. Use <nav_dir> -> <header_dir>")
    print("  <file.nav>             Single file mode. Output to <script_dir>/output_header/<map>.h")
    print("  <file.nav> <out.h>     Single file mode. Output to <out.h>")
    print("")
    print("Options:")
    print("  -h, --help             Show this help message")
    print("")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_header_dir = os.path.join(script_dir, "output_header")

    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print_help()
        return

    arg1 = sys.argv[1] if len(sys.argv) >= 2 else None
    arg2 = sys.argv[2] if len(sys.argv) >= 3 else None

    if arg1 and os.path.isfile(arg1) and arg1.lower().endswith(".nav"):
        nav_path = arg1
        map_name = sanitize_map_name(nav_path)

        if arg2:
            output_path = arg2
            if os.path.isdir(output_path):
                header_dir = output_path
                output_path = os.path.join(header_dir, f"{map_name.lower()}.h")
            else:
                header_dir = os.path.dirname(os.path.abspath(output_path))
                if header_dir:
                    os.makedirs(header_dir, exist_ok=True)
        else:
            header_dir = default_header_dir
            os.makedirs(header_dir, exist_ok=True)
            output_path = os.path.join(header_dir, f"{map_name.lower()}.h")

        write_embedded_nav_node_header(os.path.join(header_dir, "CEmbeddedNavNode.h"))

        print(f"Single-file mode: {nav_path}")
        try:
            nav = NavFile(nav_path)
            generate_header(nav, output_path, map_name)
            print(f"\nDone. Header written to: {output_path}")
        except Exception as e:
            print(f"FAILED: {nav_path}: {e}")
            sys.exit(1)
        return

    if arg1:
        nav_dir = arg1
        header_dir = arg2 if arg2 else default_header_dir
    else:
        nav_dir = os.path.join(script_dir, "output")
        header_dir = default_header_dir

    if not os.path.isdir(nav_dir):
        print(f"Error: nav directory not found: {nav_dir}")
        sys.exit(1)

    os.makedirs(header_dir, exist_ok=True)

    write_embedded_nav_node_header(os.path.join(header_dir, "CEmbeddedNavNode.h"))

    nav_files = sorted(
        f for f in os.listdir(nav_dir)
        if f.lower().endswith(".nav")
    )

    if not nav_files:
        print(f"No .nav files found in {nav_dir}")
        sys.exit(1)

    print(f"Found {len(nav_files)} .nav file(s) in {nav_dir}")
    print(f"Output directory: {header_dir}\n")

    ok = 0
    fail = 0

    for nav_filename in nav_files:
        nav_path = os.path.join(nav_dir, nav_filename)
        map_name = sanitize_map_name(nav_filename)
        output_path = os.path.join(header_dir, f"{map_name.lower()}.h")

        print("=" * 60)
        print(f"Processing: {nav_filename}")
        print("=" * 60)

        try:
            nav = NavFile(nav_path)
            generate_header(nav, output_path, map_name)
            ok += 1
        except Exception as e:
            print(f"FAILED: {nav_filename}: {e}")
            fail += 1

        print()

    print("=" * 60)
    print(f"Done. Success: {ok}, Failed: {fail}")
    print(f"Headers written to: {header_dir}")

if __name__ == "__main__":
    main()
