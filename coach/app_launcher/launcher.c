#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char executable[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0) {
        return 1;
    }

    char resolved[PATH_MAX];
    if (realpath(executable, resolved) == NULL) {
        return 1;
    }

    char path_one[PATH_MAX];
    char path_two[PATH_MAX];
    char path_three[PATH_MAX];
    snprintf(path_one, sizeof(path_one), "%s", resolved);
    snprintf(path_two, sizeof(path_two), "%s", dirname(path_one));
    snprintf(path_three, sizeof(path_three), "%s", dirname(path_two));

    char app_dir[PATH_MAX];
    snprintf(app_dir, sizeof(app_dir), "%s", dirname(path_three));
    char coach_dir[PATH_MAX];
    snprintf(coach_dir, sizeof(coach_dir), "%s", dirname(app_dir));

    char python[PATH_MAX];
    if (snprintf(python, sizeof(python), "%s/.venv312/bin/python", coach_dir) >= (int)sizeof(python)) {
        return 1;
    }
    if (access(python, X_OK) != 0 || chdir(coach_dir) != 0) {
        execl("/usr/bin/osascript", "osascript", "-e",
              "display alert \"Coach Companion is not installed\" message \"The .venv312 environment is missing. Complete the one-time setup in README.\" as critical",
              (char *)NULL);
        return 1;
    }

    execl(python, python, "-m", "coach", "app", (char *)NULL);
    return 1;
}
