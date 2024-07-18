#!/usr/bin/env python3

import argparse
import subprocess
import sys

from pathlib import Path


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, output):
    with open(path, "w") as f:
        f.write(output)


# Parse a file that looks like
#
#   FOO = foo1 foo2 foo3
#   BAR =
#   BAZ = baz1
#
# into a dictionary that looks like
#
#   {
#     "${FOO}": ["foo1", "foo2", "foo3"],
#     "${BAR}": [],
#     "${BAZ}": ["baz1"],
#   }
#
def load_values(path):
    values = {}

    with open(path) as f:
        lineno = 0
        for line in f:
            lineno += 1
            line = line.strip()

            # Skip empty lines and comments
            if line == "" or line[0] == "#":
                continue

            parts = line.split(" ")

            if len(parts) < 2 or parts[1] != "=":
                print(f"{path}:{lineno}: Invalid syntax")
                sys.exit(1)

            # Use "${FOO}" instead of "FOO" as the dictionary key.
            # This makes things more convenient later
            key = "${" + parts[0] + "}"
            value = parts[2:]

            values[key] = value

    return values


# Parse a file that looks like
#
#   #BEGIN FOO
#   foo() { touch foo }
#   #END FOO
#
#   #BEGIN BAR
#   bar() { rm -f bar }
#   #END BAR
#
# into a dictionary that looks like
#
#   {
#     "#FOO#": "foo() { touch foo }",
#     "#BAR#": "bar() { rm -f bar }",
#   }
#
def load_snippets(path):
    snippets = {}

    with open(path) as f:
        lineno = 0
        current = "NONE"
        snippet = []

        for line in f:
            lineno += 1

            # Only strip trailing whitespace to preserve indentation
            line = line.rstrip()

            # Currently not inside a snippet
            if current == "NONE":

                # Skip empty lines
                if line == "":
                    continue

                # Start of a new snippet
                if line.startswith("#BEGIN "):
                    current = "#" + line[len("#BEGIN "):] + "#"
                    continue

                # The only thing accepted outside of a snippet is the
                # start of a snippet
                print(f"{path}:{lineno}: Invalid syntax")
                sys.exit(1)

            # Currently inside a snippet
            else:

                # End of the current snippet
                if line.startswith("#END "):
                    name = "#" + line[len("#END "):] + "#"

                    # Prevent mismatched BEGIN/END
                    if name != current:
                        print(f"{path}:{lineno}: Expected {current}, got {name}")
                        sys.exit(1)

                    # Save the current snippet and start fresh
                    snippets[current] = "\n".join(snippet)
                    current = "NONE"
                    snippet = []
                    continue

                # The rest of the snippet is taken verbatim
                snippet.append(line)

        # Final sanity check
        if len(snippet) != 0 or current != "NONE":
            print(f"{path}: Last snippet was not terminated")
            sys.exit(1)

    return snippets


def process_control(path, arches):
    output = read_file(path)

    for arch in arches:
        output = output.replace(arch, " ".join(arches[arch]))

    return output


def process_maintscript(path, snippets):
    output = read_file(path)

    for snippet in snippets:
        output = output.replace(snippet, snippets[snippet])

    return output


def process_debhelper(path, arches, mode, arch, os):
    output = []

    with open(path) as f:
        lineno = 0
        for line in f:
            lineno += 1
            line = line.strip()

            # Empty lines and lines that don't start with [cond] are
            # included in the output verbatim
            if line == "" or line[0] != "[":
                output.append(line)
                continue

            parts = line[1:].split("]", maxsplit=1)

            if len(parts) < 2:
                print(f"{path}:{lineno}: Invalid syntax")
                sys.exit(1)

            # The line looked like
            #
            #   [cond] file
            #
            cond = parts[0].strip()
            file = parts[1].strip()

            # In verify mode, strip the condition and output the rest.
            # Running wrap-and-sort against this output (see below)
            # guarantees that the input follows the requirements too
            if mode == "verify":
                output.append(file)
                continue

            # Handle lines that look like
            #
            #   [linux-any] file
            #
            if cond.endswith("-any"):
                if cond == os + "-any":
                    output.append(file)
                continue

            if cond not in arches:
                print(f"{path}:{lineno}: Unknown architecture group '{cond}'")
                sys.exit(1)

            # Only output the line if we the architecture we're building on
            # is one of those listed in cond. cond itself will be stripped
            if arch in arches[cond]:
                output.append(file)

    output.append("")
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["generate", "build", "verify"],
                                  default="generate")
    parser.add_argument("--arch")
    parser.add_argument("--os")
    args = parser.parse_args()
    mode = args.mode
    arch = args.arch
    os = args.os

    if mode == "build" and (arch is None or os is None):
        print("--arch and --os are required for --mode=build")
        sys.exit(1)

    maintscript_exts = [
        ".postinst",
        ".postrm",
        ".preinst",
        ".prerm",
    ]
    debhelper_exts = [
        ".install",
    ]
    template_ext = ".in"
    debian_dir = Path("debian")
    arches_file = Path(debian_dir, "arches.mk")
    snippets_file = Path(debian_dir, "snippets.sh")

    arches = load_values(arches_file)
    snippets = load_snippets(snippets_file)

    for infile in sorted(debian_dir.glob("*")):
        infile = Path(infile)

        # Only process templates
        if infile.suffix != template_ext:
            continue

        outfile = Path(debian_dir, infile.stem)

        # Generate mode is for maintainers, and is used to keep
        # debian/control in sync with its template.
        # All other files are ignored
        if mode == "generate" and outfile.name != "control":
            continue

        print(f"  GEN {outfile}")

        # When building the package, debian/control should already be
        # in sync with its template. To confirm that is the case,
        # save the contents of the output file before regenerating it
        if mode in ["build", "verify"] and outfile.name == "control":
            old_output = read_file(outfile)

        if outfile.name == "control":
            output = process_control(infile, arches)
        elif outfile.suffix in maintscript_exts:
            output = process_maintscript(infile, snippets)
        elif outfile.suffix in debhelper_exts:
            output = process_debhelper(infile, arches, mode, arch, os)
        else:
            print(f"Unknown file type {outfile.suffix}")
            sys.exit(1)

        write_file(outfile, output)

        # When building the package, regenerating debian/control
        # should be a no-op. If that's not the case, it means that
        # the file and its template have gone out of sync, and we
        # don't know which one should be used.
        # Abort the build and let the user fix things
        if mode in ["build", "verify"] and outfile.name == "control":
            if output != old_output:
                print(f"{outfile}: Needs to be regenerated from template")
                sys.exit(1)

    # In verify mode only, check that things are pretty
    if mode == "verify":
        print("  CHK wrap-and-sort")
        wrap_and_sort = subprocess.run(["wrap-and-sort", "-ast", "--dry-run"],
                                       capture_output=True, text=True)
        if wrap_and_sort.returncode != 0 or wrap_and_sort.stdout != "":
            print("stdout:")
            print(wrap_and_sort.stdout.strip())
            print(f"rc: {wrap_and_sort.returncode}\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
