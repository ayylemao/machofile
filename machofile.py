#!/usr/bin/python

"""machofile, Mach-O file reader module

The Mach-O file format is the executable file format used 
by macOS, iOS, watchOS, and tvOS.

Inspired by pefile, this module aims to provide a similar 
capability but for Mach-O binaries instead. The basic structures 
and constant are taken from the Mach-O header file (loader.h) 
from the xnu kernel source code. Reference material and documentation 
used to gain the file format knowledge are listed below.

Reference/Documentation links:
- https://opensource.apple.com/source/xnu/xnu-2050.18.24/EXTERNAL_HEADERS/mach-o/loader.h
- https://github.com/apple-oss-distributions/lldb/blob/10de1840defe0dff10b42b9c56971dbc17c1f18c/llvm/include/llvm/Support/MachO.h
- https://iphonedev.wiki/Mach-O_File_Format
- https://lowlevelbits.org/parsing-mach-o-files/
- https://github.com/aidansteele/osx-abi-macho-file-format-reference
- https://lief-project.github.io/doc/latest/tutorials/11_macho_modification.html
- https://github.com/VirusTotal/yara/blob/master/libyara/include/yara/macho.h

Copyright (c) 2023 Pasquale Stirparo <pstirparo@threatresearch.ch>
"""

# struct mach_header {
#     uint32_t      magic;
#     cpu_type_t    cputype;
#     cpu_subtype_t cpusubtype;
#     uint32_t      filetype;
#     uint32_t      ncmds;
#     uint32_t      sizeofcmds;
#     uint32_t      flags;
#     uint32_t      reserved;  // This is the additional field for 64-bit
# };

# struct load_command {
#     uint32_t cmd;
#     uint32_t cmdsize;
# };

# struct segment_command {
#     uint32_t    cmd;
#     uint32_t    cmdsize;
#     struct segment_command { // for 32-bit architectures
#         char        segname[16];
#         uint32_t    vmaddr;
#         uint32_t    vmsize;
#         uint32_t    fileoff;
#         uint32_t    filesize;
#         vm_prot_t   maxprot;
#         vm_prot_t   initprot;
#         uint32_t    nsects;
#         uint32_t    flags;
#     } segment_command;
# };

# struct dylib_command {
#     uint32_t cmd;
#     uint32_t cmdsize;
#     struct dylib {
#         union lc_str name;
#         uint32_t timestamp;
#         uint32_t current_version;
#         uint32_t compatibility_version;
#     } dylib;
# };

__author__ = "Pasquale Stirparo"
__version__ = "2023.10.10 alpha"
__contact__ = "pstirparo@threatresearch.ch"

import argparse
from hashlib import sha256
from hashlib import md5
import struct


def two_way_dict(pairs):
    return dict([(e[1], e[0]) for e in pairs] + pairs)


# Mach-O header formats
MACHO_HEADER_FORMAT_32 = "IiiIIII"
MACHO_HEADER_FORMAT_64 = "IiiIIIII"
LOAD_COMMAND_FORMAT = "II"
SEGMENT_COMMAND_FORMAT_32 = "16sIIIIIIII"
SEGMENT_COMMAND_FORMAT_64 = "16sQQQQIIII"
DYLIB_COMMAND_FORMAT = "IIII"

# Mach-O constants and mappings
MH_MAGIC = 0xFEEDFACE  # Big endian, 32 bit Mach-O
MH_CIGAM = 0xCEFAEDFE  # Little endian, 32 bit Mach-O
MH_MAGIC_64 = 0xFEEDFACF  # Big endian, 64 bit Mach-O
MH_CIGAM_64 = 0xCFFAEDFE  # Little endian, 64 bit Mach-O

MAGIC_MAP = {
    MH_MAGIC: "MH_MAGIC (32-bit)",
    MH_CIGAM: "MH_CIGAM (32-bit reversed)",
    MH_MAGIC_64: "MH_MAGIC_64 (64-bit)",
    MH_CIGAM_64: "MH_CIGAM_64 (64-bit reversed)",
}

# Mach-O universal binary magic constants
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF
FAT_CIGAM_64 = 0xBFBAFECA

FAT_MAGIC_MAP = {
    FAT_MAGIC: "FAT_MAGIC (32-bit)",
    FAT_CIGAM: "FAT_CIGAM (32-bit reversed)",
    FAT_MAGIC_64: "FAT_MAGIC_64 (64-bit)",
    FAT_CIGAM_64: "FAT_CIGAM_64 (64-bit reversed)",
}

# CPU masks, types and mappings
CPU_ARCH_MASK = 0xFF000000  # Mask for architecture bits
CPU_ARCH_ABI64 = 0x01000000  # 64-bit ABI mask (for cputype)
CPU_SUBTYPE_LIB64 = 0x80000000  # 64-bit library mask (for cpusubtype)

# Mach-O CPU Types
CPU_TYPE_X86 = 0x7
CPU_TYPE_X86_64 = 0x1000007
CPU_TYPE_ARM = 0xC
CPU_TYPE_ARM64 = 0x100000C
CPU_TYPE_PPC = 0x12
CPU_TYPE_PPC64 = 0x10000012
CPU_TYPE_SPARC = 0x14
CPU_TYPE_I860 = 0x15
CPU_TYPE_I386 = 0x7
CPU_TYPE_MC680X0 = 0x6
CPU_TYPE_MC98000 = 0xA
CPU_TYPE_HPPA = 0xB
CPU_TYPE_MC88000 = 0xD
CPU_TYPE_ALPHA = 0x10

CPU_TYPE_MAP = {
    CPU_TYPE_X86: "x86",
    CPU_TYPE_X86_64: "x86_64",
    CPU_TYPE_ARM: "ARM",
    CPU_TYPE_ARM64: "ARM 64-bit",
    CPU_TYPE_PPC: "PowerPC",
    CPU_TYPE_PPC64: "PowerPC 64-bit",
    CPU_TYPE_SPARC: "SPARC",
    CPU_TYPE_I860: "Intel i860",
    CPU_TYPE_I386: "Intel i386",
    CPU_TYPE_MC680X0: "Motorola 68000",
    CPU_TYPE_MC98000: "Motorola PowerPC",
    CPU_TYPE_HPPA: "HP PA-RISC",
    CPU_TYPE_MC88000: "Motorola 88000",
    CPU_TYPE_ALPHA: "DEC Alpha",
}

CPU_SUB_TYPE_MAP = {
    3: "x86_ALL",
    4: "x86_ARCH1",
    8: "x86_64_ALL",
    9: "x86_64_H",
    10: "x86_64_LIB64",
}

# list comprehensive but still incomplete. tbd.
cpu_subtypes = [
    ("CPU_SUBTYPE_386", 0x3),
    ("CPU_SUBTYPE_486", 0x4),
    ("CPU_SUBTYPE_486SX", 0x84),
    ("CPU_SUBTYPE_586", 0x5),
    ("CPU_SUBTYPE_PENT", 0x5),
    ("CPU_SUBTYPE_PENTPRO", 0x16),
    ("CPU_SUBTYPE_PENTII_M3", 0x36),
    ("CPU_SUBTYPE_PENTII_M5", 0x56),
    ("CPU_SUBTYPE_CELERON", 0x67),
    ("CPU_SUBTYPE_CELERON_MOBILE", 0x77),
    ("CPU_SUBTYPE_PENTIUM_3", 0x8),
    ("CPU_SUBTYPE_PENTIUM_3_M", 0x18),
    ("CPU_SUBTYPE_PENTIUM_3_XEON", 0x28),
    ("CPU_SUBTYPE_PENTIUM_M", 0x9),
    ("CPU_SUBTYPE_PENTIUM_4", 0xA),
    ("CPU_SUBTYPE_PENTIUM_4_M", 0x1A),
    ("CPU_SUBTYPE_ITANIUM", 0xB),
    ("CPU_SUBTYPE_ITANIUM_2", 0x1B),
    ("CPU_SUBTYPE_XEON", 0xC),
    ("CPU_SUBTYPE_XEON_MP", 0x1C),
    ("CPU_SUBTYPE_ARM_ALL", 0x0),
    ("CPU_SUBTYPE_ARM_V4T", 0x5),
    ("CPU_SUBTYPE_ARM_V6", 0x6),
    ("CPU_SUBTYPE_ARM_V5", 0x7),
    ("CPU_SUBTYPE_ARM_V5TEJ", 0x7),
    ("CPU_SUBTYPE_ARM_XSCALE", 0x8),
    ("CPU_SUBTYPE_ARM_V7", 0x9),
    ("CPU_SUBTYPE_ARM_V7F", 0xA),
    ("CPU_SUBTYPE_ARM_V7S", 0xB),
    ("CPU_SUBTYPE_ARM_V7K", 0xC),
    ("CPU_SUBTYPE_ARM_V6M", 0xE),
    ("CPU_SUBTYPE_ARM_V7M", 0xF),
    ("CPU_SUBTYPE_ARM_V7EM", 0x10),
    ("CPU_SUBTYPE_ARM_V8", 0xD),
    ("CPU_SUBTYPE_ARM64_ALL", 0x0),
    ("CPU_SUBTYPE_ARM64_V8", 0x1),
]

CPU_SUBTYPE_MAP = two_way_dict(cpu_subtypes)

# Mach-O header filetypes
macho_header_filetype = [
    ("MH_OBJECT", 0x1),
    ("MH_EXECUTE", 0x2),
    ("MH_FVMLIB", 0x3),
    ("MH_CORE", 0x4),
    ("MH_PRELOAD", 0x5),
    ("MH_DYLIB", 0x6),
    ("MH_DYLINKER", 0x7),
    ("MH_BUNDLE", 0x8),
    ("MH_DYLIB_STUB", 0x9),
    ("MH_DSYM", 0xA),
    ("MH_KEXT_BUNDLE", 0xB),
]

MACHO_FILETYPE = two_way_dict(macho_header_filetype)

FLAGS_MAP = {
    0x1: "MH_NOUNDEFS",
    0x2: "MH_INCRLINK",
    0x4: "MH_DYLDLINK",
    0x8: "MH_BINDATLOAD",
    0x10: "MH_PREBOUND",
    0x20: "MH_SPLIT_SEGS",
    0x40: "MH_LAZY_INIT",
    0x80: "MH_TWOLEVEL",
    0x100: "MH_FORCE_FLAT",
    0x200: "MH_NOMULTIDEFS",
    0x400: "MH_NOFIXPREBINDING",
    0x800: "MH_PREBINDABLE",
    0x1000: "MH_ALLMODSBOUND",
    0x2000: "MH_SUBSECTIONS_VIA_SYMBOLS",
    0x4000: "MH_CANONICAL",
    0x8000: "MH_WEAK_DEFINES",
    0x10000: "MH_BINDS_TO_WEAK",
    0x20000: "MH_ALLOW_STACK_EXECUTION",
    0x40000: "MH_ROOT_SAFE",
    0x80000: "MH_SETUID_SAFE",
    0x100000: "MH_NO_REEXPORTED_DYLIBS",
    0x200000: "MH_PIE",
    0x400000: "MH_DEAD_STRIPPABLE_DYLIB",
    0x800000: "MH_HAS_TLV_DESCRIPTORS",
    0x1000000: "MH_NO_HEAP_EXECUTION",
    0x2000000: "MH_APP_EXTENSION_SAFE",
    0x4000000: "MH_NLIST_OUTOFSYNC_WITH_DYLDINFO",
    0x8000000: "MH_SIM_SUPPORT",
    0x80000000: "MH_DYLIB_IN_CACHE",
}

# Constants for the "cmd" field in the load command structure
load_command_types = [
    ("LC_SEGMENT", 0x1),
    ("LC_SYMTAB", 0x2),
    ("LC_SYMSEG", 0x3),
    ("LC_THREAD", 0x4),
    ("LC_UNIXTHREAD", 0x5),
    ("LC_LOADFVMLIB", 0x6),
    ("LC_IDFVMLIB", 0x7),
    ("LC_IDENT", 0x8),
    ("LC_FVMFILE", 0x9),
    ("LC_PREPAGE", 0xA),
    ("LC_DYSYMTAB", 0xB),
    ("LC_LOAD_DYLIB", 0xC),
    ("LC_ID_DYLIB", 0xD),
    ("LC_LOAD_DYLINKER", 0xE),
    ("LC_ID_DYLINKER", 0xF),
    ("LC_PREBOUND_DYLIB", 0x10),
    ("LC_ROUTINES", 0x11),
    ("LC_SUB_FRAMEWORK", 0x12),
    ("LC_SUB_UMBRELLA", 0x13),
    ("LC_SUB_CLIENT", 0x14),
    ("LC_SUB_LIBRARY", 0x15),
    ("LC_TWOLEVEL_HINTS", 0x16),
    ("LC_PREBIND_CKSUM", 0x17),
    ("LC_LOAD_WEAK_DYLIB", 0x18 | 0x80000000),
    ("LC_SEGMENT_64", 0x19),
    ("LC_ROUTINES_64", 0x1A),
    ("LC_UUID", 0x1B),
    ("LC_RPATH", 0x1C | 0x80000000),
    ("LC_CODE_SIGNATURE", 0x1D),
    ("LC_SEGMENT_SPLIT_INFO", 0x1E),
    ("LC_REEXPORT_DYLIB", 0x1F | 0x80000000),
    ("LC_LAZY_LOAD_DYLIB", 0x20),
    ("LC_ENCRYPTION_INFO", 0x21),
    ("LC_DYLD_INFO", 0x22),
    ("LC_DYLD_INFO_ONLY", 0x22 | 0x80000000),
    ("LC_LOAD_UPWARD_DYLIB", 0x23 | 0x80000000),
    ("LC_VERSION_MIN_MACOSX", 0x24),
    ("LC_VERSION_MIN_IPHONEOS", 0x25),
    ("LC_FUNCTION_STARTS", 0x26),
    ("LC_DYLD_ENVIRONMENT", 0x27),
    ("LC_MAIN", 0x28 | 0x80000000),
    ("LC_DATA_IN_CODE", 0x29),
    ("LC_SOURCE_VERSION", 0x2A),
    ("LC_DYLIB_CODE_SIGN_DRS", 0x2B),
    ("LC_LINKER_OPTIONS", 0x2D),
    ("LC_LINKER_OPTIMIZATION_HINT", 0x2E),
    ("LC_VERSION_MIN_TVOS", 0x2F),
    ("LC_VERSION_MIN_WATCHOS", 0x30),
]

LOAD_COMMAND_TYPES = two_way_dict(load_command_types)

dylib_command_types = [
    ("LC_ID_DYLIB", 0xD),
    ("LC_LOAD_DYLIB", 0xC),
    ("LC_LOAD_WEAK_DYLIB", 0x18),
]

DYLIB_CMD_TYPES = two_way_dict(dylib_command_types)


def decode_cpusubtype(cputype, cpusubtype_value):
    mask = 0xFFFFFFFF  # to get unsigned value
    cpusubtype_value = cpusubtype_value & mask
    decoded_subtypes = []

    # Check if the cpusubtype is combined or singular
    for subtype, subtype_name in CPU_SUB_TYPE_MAP.items():
        if cpusubtype_value & subtype:
            decoded_subtypes.append(subtype_name)
    return ", ".join(decoded_subtypes) if decoded_subtypes else str(cpusubtype_value)


def decode_flags(flags_value):
    decoded_flags = []
    for flag, flag_name in FLAGS_MAP.items():
        if flags_value & flag:
            decoded_flags.append(flag_name)
    return ", ".join(decoded_flags) if decoded_flags else str(flags_value)


# This function receives a dictionary as input and prints it in a nice readable way
def print_dict(d):
    for k, v in d.items():
        print(f"\t{k}: {v}")


# This function receives a list as input and prints it in a nice readable way
def print_list(l):
    for i in l:
        print(f"\t{i}")


def get_general_info(data):
    md5_hash = md5()
    sha256_hash = sha256()
    md5_hash.update(data)
    sha256_hash.update(data)
    return {"MD5: ": md5_hash.hexdigest(), "SHA256: ": sha256_hash.hexdigest()}


def get_macho_header(f):
    f.seek(0)
    # Read the magic value to determine byte order
    magic = struct.unpack("I", f.read(4))[0]
    byte_order = ">" if magic in {MH_CIGAM, MH_CIGAM_64} else "<"  # endianness

    # Position back to start of file for full header read
    f.seek(0)
    if magic in {MH_MAGIC, MH_CIGAM}:
        header_size = struct.calcsize(byte_order + MACHO_HEADER_FORMAT_32)
        header_data = f.read(header_size)
        header = struct.unpack(byte_order + MACHO_HEADER_FORMAT_32, header_data)
    else:
        header_size = struct.calcsize(byte_order + MACHO_HEADER_FORMAT_64)
        header_data = f.read(header_size)
        header = struct.unpack(byte_order + MACHO_HEADER_FORMAT_64, header_data)

    header_dict = {
        "magic": MAGIC_MAP.get(header[0], header[0]),
        "cputype": CPU_TYPE_MAP.get(header[1], header[1]),
        "cpusubtype": decode_cpusubtype(header[1], header[2]),
        "filetype": MACHO_FILETYPE[header[3]],
        "ncmds": header[4],
        "sizeofcmds": header[5],
        "flags": decode_flags(header[6]),
    }

    return header_dict


def get_macho_load_cmd_table(f):
    load_commands = []
    f.seek(0)
    # Read the magic value to determine byte order and architecture
    magic = struct.unpack("I", f.read(4))[0]
    byte_order = ">" if magic in {MH_CIGAM, MH_CIGAM_64} else "<"  # endianness

    # Depending on architecture, read the correct Mach-O header
    f.seek(0)
    if magic in {MH_MAGIC, MH_CIGAM}:
        header_size = struct.calcsize(byte_order + MACHO_HEADER_FORMAT_32)
    else:
        header_size = struct.calcsize(byte_order + MACHO_HEADER_FORMAT_64)

    header_data = f.read(header_size)
    if magic in {MH_MAGIC, MH_CIGAM}:
        _, _, _, filetype, ncmds, sizeofcmds, _ = struct.unpack(
            byte_order + MACHO_HEADER_FORMAT_32, header_data
        )
    else:
        _, _, _, filetype, ncmds, sizeofcmds, _, _ = struct.unpack(
            byte_order + MACHO_HEADER_FORMAT_64, header_data
        )

    # Parse each load command
    for _ in range(ncmds):
        cmd_data = f.read(struct.calcsize(byte_order + LOAD_COMMAND_FORMAT))
        cmd, cmdsize = struct.unpack(byte_order + LOAD_COMMAND_FORMAT, cmd_data)
        load_commands.append({"cmd": LOAD_COMMAND_TYPES[cmd], "cmdsize": cmdsize})
        # Move the file pointer past this load command to the start of the next one
        f.seek(f.tell() + cmdsize - struct.calcsize(byte_order + LOAD_COMMAND_FORMAT))

    loadcommans_set = set(load_command["cmd"] for load_command in load_commands)
    if "LC_SEGMENT_64" in loadcommans_set:
        loadcommans_set.remove("LC_SEGMENT_64")
    if "LC_SEGMENT" in loadcommans_set:
        loadcommans_set.remove("LC_SEGMENT")

    return load_commands, loadcommans_set


def get_file_segments(f):
    f.seek(0)
    segments = []

    magic = struct.unpack("I", f.read(4))[0]
    is_64_bit = True if magic in {MH_MAGIC_64, MH_CIGAM_64} else False
    byte_order = ">" if magic in {MH_CIGAM, MH_CIGAM_64} else "<"  # endianness

    # Adjust the position to skip cputype and cpusubtype
    f.seek(12, 1)

    # Get number of load commands from header
    ncmds = struct.unpack("I", f.read(4))[0]

    # Skip over the rest of the Mach-O header to reach load commands
    if is_64_bit:
        f.seek(12, 1)  # Skip the remainder of the 64-bit Mach-O header
    else:
        f.seek(8, 1)  # Skip the remainder of the 32-bit Mach-O header

    # Process each load command
    for _ in range(ncmds):
        # Read command type and size
        cmd, cmdsize = struct.unpack(byte_order + LOAD_COMMAND_FORMAT, f.read(8))

        # If it's an LC_SEGMENT, process it
        if (
            cmd == LOAD_COMMAND_TYPES["LC_SEGMENT"]
            or cmd == LOAD_COMMAND_TYPES["LC_SEGMENT_64"]
        ):
            if is_64_bit:
                segment_size = struct.calcsize(byte_order + SEGMENT_COMMAND_FORMAT_64)
                seg_data = f.read(segment_size)
                (
                    segname,
                    vaddr,
                    vsize,
                    offset,
                    size,
                    max_vm_protection,
                    initial_vm_protection,
                    nsectors,
                    flags,
                ) = struct.unpack(SEGMENT_COMMAND_FORMAT_64, seg_data)
            else:
                segment_size = struct.calcsize(byte_order + SEGMENT_COMMAND_FORMAT_32)
                seg_data = f.read(segment_size)
                (
                    segname,
                    vaddr,
                    vsize,
                    offset,
                    size,
                    max_vm_protection,
                    initial_vm_protection,
                    nsectors,
                    flags,
                ) = struct.unpack(SEGMENT_COMMAND_FORMAT_32, seg_data)
            segname = segname.decode("utf-8").rstrip("\0")
            tmp_dict = {
                "segname": segname,
                "vaddr": vaddr,
                "vsize": vsize,
                "offset": offset,
                "size": size,
                "max_vm_protection": max_vm_protection,
                "initial_vm_protection": initial_vm_protection,
                "nsects": nsectors,
                "flags": flags,
            }
            segments.append((tmp_dict))
            # Move to the next command
            f.seek(cmdsize - segment_size - 8, 1)
        else:
            # Move to the next command
            f.seek(cmdsize - 8, 1)
    return segments


def get_dylib_commands(f):
    f.seek(0)
    dylib_full_info = []
    dylib_names = []

    magic = struct.unpack("I", f.read(4))[0]
    is_64_bit = True if magic in {MH_MAGIC_64, MH_CIGAM_64} else False
    byte_order = ">" if magic in {MH_CIGAM, MH_CIGAM_64} else "<"  # endianness

    # Adjust the position to skip cputype and cpusubtype
    f.seek(12, 1)

    # Get number of load commands from header
    ncmds = struct.unpack("I", f.read(4))[0]

    # Skip over the rest of the Mach-O header to reach load commands
    if is_64_bit:
        f.seek(12, 1)  # Skip the remainder of the 64-bit Mach-O header
    else:
        f.seek(8, 1)  # Skip the remainder of the 32-bit Mach-O header

    # Process each load command
    for _ in range(ncmds):
        # Read command type and size
        cmd, cmdsize = struct.unpack(byte_order + LOAD_COMMAND_FORMAT, f.read(8))

        # If it's an LC_SEGMENT, process it
        if cmd in DYLIB_CMD_TYPES:
            dylib_size = struct.calcsize(byte_order + DYLIB_COMMAND_FORMAT)
            dylib_data = f.read(dylib_size)
            (
                dylib_name_offset,
                dylib_timestamp,
                dylib_current_version,
                dylib_compat_version,
            ) = struct.unpack(DYLIB_COMMAND_FORMAT, dylib_data)

            dylib_name_size = cmdsize - dylib_name_offset
            dylib_name = f.read(dylib_name_size).rstrip(b"\x00")
            tmp_dict = {
                "dylib_name_offset": dylib_name_offset,
                "dylib_timestamp": dylib_timestamp,
                "dylib_current_version": dylib_current_version,
                "dylib_compat_version": dylib_compat_version,
                "dylib_name": dylib_name,
            }
            dylib_full_info.append((tmp_dict))
            dylib_names.append(dylib_name)
        else:
            # Move to the next command
            f.seek(cmdsize - 8, 1)
    return dylib_full_info, dylib_names


def main():
    # # Set up argparse... placeholder more options to come
    parser = argparse.ArgumentParser(description="Parse Mach-O file structures.")
    parser.add_argument(
        "-f", "--file", type=str, help="Path to the file to be parsed", required=True
    )

    args = parser.parse_args()
    file_path = args.file

    with open(file_path, "rb") as f:
        magic = struct.unpack("I", f.read(4))[0]
        if magic in MAGIC_MAP:
            f.seek(0)
            data = f.read()
            print("\nGetting general info...")
            print_dict(get_general_info(data))

            print("\nParsing Mac-O Header...")
            print_dict(get_macho_header(f))

            print("\nParsing Load Cmd table...")
            loadcommands, loadcommands_set = get_macho_load_cmd_table(f)
            print_list(loadcommands)

            print("\nLoad Commands:")
            print_list(sorted(loadcommands_set))

            print("\nFile Segments:")
            segments = get_file_segments(f)
            for seg in segments:
                print_dict(seg)
                print("")

            print("\nParsing Dylib Cmd table...")
            dylib_full_info, dylib_names = get_dylib_commands(f)
            for dylib in dylib_full_info:
                print_dict(dylib)
                print("")

            print("\nParsing Dylib List...")
            print_list(dylib_names)
        else:
            raise ValueError("Not a valid Mach-O file")


if __name__ == "__main__":
    main()