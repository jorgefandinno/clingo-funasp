PACKAGE=clingo_funasp
sed -i "s/from clingo import/from ${PACKAGE} import/g" lib/python-api/tests/*.py
sed -i "s/clingo\./${PACKAGE}\./g" lib/python-api/tests/*.py
sed -i "s/from clingo import/from ${PACKAGE} import/g" lib/python-api/stubs/*.pyi
sed -i "s/clingo\./${PACKAGE}\./g" lib/python-api/stubs/*.pyi