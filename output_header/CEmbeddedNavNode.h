#pragma once

#include "Source/Sdk/Datatypes/Vector.h"

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
