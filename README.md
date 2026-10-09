# CS2 NaviGation Dumper

A Python tool that parses CS2 `.nav` files and exports the navigation mesh as C++ header files, ready to be embedded into your own project.

## Features

- Automatically parses CS2 `.nav` files (version 35 and 36)
- Supports both official and community maps
- Extracts nav areas, polygons, and connections
- Generates a compact `CEmbeddedNavNode` array for each map
- No external dependencies, pure Python standard library

## Requirements

- Python 3.7+
- A `Vector3` type in your C++ project (see below)

## Usage

### Batch mode

Process every `.nav` file in a directory:

```text
python NaviGation-To-Header.py <nav_dir> <header_dir>
```

Example:

```text
python NaviGation-To-Header.py ./output ./output_header
```

If no arguments are given, the script defaults to:

- Input:  `<script_dir>/output`
- Output: `<script_dir>/output_header`

### Single file mode

Process a single `.nav` file:

```text
python NaviGation-To-Header.py <file.nav>
python NaviGation-To-Header.py <file.nav> <out.h>
```

### Help

```text
python NaviGation-To-Header.py --help
```

## Output

For each `.nav` file, a corresponding `.h` file is generated, for example:

```text
output_header/
CEmbeddedNavNode.h
cs_office.h
de_dust2.h
de_mirage.h
...
```

Each map header contains an array of nav nodes and a node count:

```cpp
static const CEmbeddedNavNode CS_OFFICE_NAV_DATA[] = 
{
    {
        0,
        123.456789f,
        {1.000000f, 2.000000f, 3.000000f},
        4,
        {1, 2, 3, 4, 0, 0, ...},
        {10.5f, 12.3f, 8.8f, 9.1f, 0.0f, ...},
    },
    ...
};

static const int CS_OFFICE_NAV_NODE_COUNT = 3680;
```

### CEmbeddedNavNode

The generated headers reference a `CEmbeddedNavNode` type. A minimal definition looks like this:

```cpp
#pragma once

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
```

**Important:** You need to include your own `Vector3` library. This project does not provide one. Adjust the include path and the type name to match your own project.

The script will automatically write a `CEmbeddedNavNode.h` into the output directory. If you already have your own version, either remove the write step or point it at a template file.

## How it works

- Reads the `.nav` file header to determine the format version.
- Locates the polygon and area sections.
- Parses nav areas, including their corners and edge connections.
- Builds a neighbor graph based on shared edges and distance.
- Filters out isolated nodes.
- Emits a C++ header with a flat array of `CEmbeddedNavNode`.

The area search uses a fast `bytes.find` scan combined with a deep validation pass, which handles both version 35 and 36 files reliably.

## Notes

- The script assumes that the first nav area has `id == 1`. This holds for all currently known official maps.
- Up to 16 neighbors are stored per node. Extra neighbors are dropped, keeping the closest ones by distance.
- Isolated nodes (no neighbors) are excluded from the output.
