BRANCH=$(git branch --show-current) && \
git fetch --all && \
git checkout -b ${BRANCH}-backup && \
git checkout wip-20 && \
git pull && \
git checkout ${BRANCH} && \
MESSAGE=$(git log -1 --pretty=%B) && \
AUTHOR=$(git log -2 --pretty=%an | tail -1) && \
[ "${AUTHOR}" = "Roland Kaminski" ]
EXIT_CODE=$?
if [ ${EXIT_CODE} -ne 0 ]; then
    echo "An error occurred in the first part. Aborting."
    exit 1
fi
git checkout wip-20 -- lib/python-api/stubs/*.pyi
git checkout wip-20 -- lib/python-api/tests/*.py
git reset --soft HEAD~1 && \
git commit -am"Preparing to rebase: copying changes from wip-20 to lib/python-api/tests/*.py" && \
git rebase wip-20 && \
git reset --soft HEAD~1 && \
./update-pytest.sh && \
git commit -am"${MESSAGE}"