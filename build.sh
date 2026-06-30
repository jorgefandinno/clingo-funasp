cmake -S . -B build -G "Ninja Multi-Config" \
    -DCMAKE_INSTALL_PREFIX="$CONDA_PREFIX" \
    -DCLINGO_BUILD_TESTS=On \
    -DCLINGO_BUILD_APP=On \
    -DCLINGO_BUILD_EXAMPLES=On \
    -DCLASP_BUILD_TESTS=On \
    -DCLASP_BUILD_EXAMPLES=On \
    -DLIB_POTASSCO_BUILD_TESTS=On && \
cmake --build build --config Release && \
cmake --install build --config Release && \
clingo --version && \
clasp --version && \
lpconvert --version