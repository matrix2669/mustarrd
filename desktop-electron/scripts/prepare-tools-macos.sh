#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TOOLS_ROOT="${REPO_ROOT}/desktop-electron/tools"

ARCH_RAW="$(uname -m)"
case "${ARCH_RAW}" in
  arm64) ARCH="arm64" ;;
  x86_64) ARCH="x64" ;;
  *) ARCH="${ARCH_RAW}" ;;
esac

PLATFORM_DIR="darwin-${ARCH}"
DEST_DIR="${TOOLS_ROOT}/${PLATFORM_DIR}"
LIB_DIR="${DEST_DIR}/lib"
STATE_DIR="${DEST_DIR}/.build"
MANIFEST="${DEST_DIR}/manifest.txt"
CACHE_SCHEMA_VERSION="2"
FORCE_REBUILD=0

mkdir -p "${TOOLS_ROOT}"

for arg in "$@"; do
  case "${arg}" in
    --force|-f)
      FORCE_REBUILD=1
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Usage: $(basename "$0") [--force]" >&2
      exit 1
      ;;
  esac
done

required_cmds=(otool install_name_tool)
for cmd in "${required_cmds[@]}"; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
done

file_mtime() {
  local path="$1"
  stat -f "%m" "${path}"
}

file_size() {
  local path="$1"
  stat -f "%z" "${path}"
}

manifest_value() {
  local key="$1"
  local manifest_path="$2"
  local line
  line="$(grep -E "^${key}=" "${manifest_path}" | head -n 1 || true)"
  printf "%s" "${line#*=}"
}

source_fingerprint_matches() {
  local key_prefix="$1"
  local source_path="$2"
  local manifest_path="$3"
  local expected_source
  local expected_mtime
  local expected_size
  local actual_mtime
  local actual_size

  expected_source="$(manifest_value "${key_prefix}_source" "${manifest_path}")"
  expected_mtime="$(manifest_value "${key_prefix}_source_mtime" "${manifest_path}")"
  expected_size="$(manifest_value "${key_prefix}_source_size" "${manifest_path}")"
  actual_mtime="$(file_mtime "${source_path}")"
  actual_size="$(file_size "${source_path}")"

  [[ "${expected_source}" == "${source_path}" ]] && \
  [[ "${expected_mtime}" == "${actual_mtime}" ]] && \
  [[ "${expected_size}" == "${actual_size}" ]]
}

resolve_first_executable() {
  local candidate
  for candidate in "$@"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      printf "%s\n" "${candidate}"
      return 0
    fi
  done
  return 1
}

resolve_dep_path() {
  local dep="$1"
  local base
  local candidate

  if [[ -f "${dep}" ]]; then
    printf "%s\n" "${dep}"
    return 0
  fi

  base="$(basename "${dep}")"

  candidate="$(find /opt/homebrew/Cellar -name "${base}" \( -type f -o -type l \) 2>/dev/null | head -n 1 || true)"
  if [[ -n "${candidate}" && -f "${candidate}" ]]; then
    printf "%s\n" "${candidate}"
    return 0
  fi

  candidate="$(find /usr/local/Cellar -name "${base}" \( -type f -o -type l \) 2>/dev/null | head -n 1 || true)"
  if [[ -n "${candidate}" && -f "${candidate}" ]]; then
    printf "%s\n" "${candidate}"
    return 0
  fi

  return 1
}

resolve_dep_for_file() {
  local source_file="$1"
  local dep="$2"
  local source_dir
  local candidate
  local base

  if [[ "${dep}" == /System/* || "${dep}" == /usr/lib/* ]]; then
    return 1
  fi

  source_dir="$(cd "$(dirname "${source_file}")" && pwd)"

  if [[ "${dep}" == @loader_path/* ]]; then
    candidate="${source_dir}/${dep#@loader_path/}"
    if [[ -f "${candidate}" ]]; then
      printf "%s\n" "${candidate}"
      return 0
    fi
  fi

  if [[ "${dep}" == @executable_path/* ]]; then
    candidate="${DEST_DIR}/${dep#@executable_path/}"
    if [[ -f "${candidate}" ]]; then
      printf "%s\n" "${candidate}"
      return 0
    fi
  fi

  if [[ "${dep}" == @rpath/* || "${dep}" == @loader_path/* || "${dep}" == @executable_path/* ]]; then
    base="$(basename "${dep}")"
    candidate="${LIB_DIR}/${base}"
    if [[ -f "${candidate}" ]]; then
      printf "%s\n" "${candidate}"
      return 0
    fi
    resolve_dep_path "${base}" && return 0
    return 1
  fi

  resolve_dep_path "${dep}" && return 0
  return 1
}

copy_binary() {
  local source="$1"
  local name="$2"
  cp -f "${source}" "${DEST_DIR}/${name}"
  chmod +x "${DEST_DIR}/${name}"
}

copy_dep_recursive() {
  local file_path="$1"
  local dep
  local resolved
  local base
  local target

  while IFS= read -r dep; do
    [[ -z "${dep}" ]] && continue
    [[ "${dep}" == /System/* ]] && continue
    [[ "${dep}" == /usr/lib/* ]] && continue

    if ! resolved="$(resolve_dep_for_file "${file_path}" "${dep}")"; then
      echo "Warning: unable to resolve dependency ${dep}" >&2
      printf "%s\n" "${dep}" >> "${UNRESOLVED_LIST}"
      continue
    fi

    base="$(basename "${resolved}")"
    target="${LIB_DIR}/${base}"
    if [[ ! -f "${target}" ]]; then
      cp -fL "${resolved}" "${target}"
      chmod u+w "${target}" || true
    fi

    if ! grep -Fxq "${base}" "${COPIED_LIST}"; then
      printf "%s\n" "${base}" >> "${COPIED_LIST}"
      copy_dep_recursive "${target}"
    fi
  done < <(otool -L "${file_path}" | tail -n +2 | awk '{print $1}')
}

patch_binary_deps() {
  local file_path="$1"
  local dep
  local resolved
  local base

  while IFS= read -r dep; do
    [[ -z "${dep}" ]] && continue
    [[ "${dep}" == /System/* ]] && continue
    [[ "${dep}" == /usr/lib/* ]] && continue

    if ! resolved="$(resolve_dep_for_file "${file_path}" "${dep}")"; then
      continue
    fi
    base="$(basename "${resolved}")"
    if [[ -f "${LIB_DIR}/${base}" ]]; then
      install_name_tool -change "${dep}" "@loader_path/lib/${base}" "${file_path}" || true
    fi
  done < <(otool -L "${file_path}" | tail -n +2 | awk '{print $1}')
}

patch_library_deps() {
  local file_path="$1"
  local dep
  local resolved
  local base

  install_name_tool -id "@loader_path/$(basename "${file_path}")" "${file_path}" || true

  while IFS= read -r dep; do
    [[ -z "${dep}" ]] && continue
    [[ "${dep}" == /System/* ]] && continue
    [[ "${dep}" == /usr/lib/* ]] && continue

    if ! resolved="$(resolve_dep_for_file "${file_path}" "${dep}")"; then
      continue
    fi
    base="$(basename "${resolved}")"
    if [[ -f "${LIB_DIR}/${base}" ]]; then
      install_name_tool -change "${dep}" "@loader_path/${base}" "${file_path}" || true
    fi
  done < <(otool -L "${file_path}" | tail -n +2 | awk '{print $1}')
}

FFMPEG_SRC="$(resolve_first_executable \
  "/opt/homebrew/opt/ffmpeg@6/bin/ffmpeg" \
  "/usr/local/opt/ffmpeg@6/bin/ffmpeg" \
  "$(command -v ffmpeg || true)" \
)"
if [[ -z "${FFMPEG_SRC}" ]]; then
  echo "Required tool not found: ffmpeg" >&2
  exit 1
fi

FFPROBE_SRC="$(resolve_first_executable \
  "/opt/homebrew/opt/ffmpeg@6/bin/ffprobe" \
  "/usr/local/opt/ffmpeg@6/bin/ffprobe" \
  "$(command -v ffprobe || true)" \
)"
if [[ -z "${FFPROBE_SRC}" ]]; then
  echo "Required tool not found: ffprobe" >&2
  exit 1
fi

COMSKIP_SRC="$(resolve_first_executable "$(command -v comskip || true)")"
if [[ -z "${COMSKIP_SRC}" ]]; then
  echo "Required tool not found: comskip" >&2
  exit 1
fi

if [[ "${FORCE_REBUILD}" != "1" ]] && [[ -f "${MANIFEST}" ]] && \
   [[ -x "${DEST_DIR}/ffmpeg" ]] && [[ -x "${DEST_DIR}/ffprobe" ]] && [[ -x "${DEST_DIR}/comskip" ]]; then
  cached_schema="$(manifest_value "schema_version" "${MANIFEST}")"
  cached_arch="$(manifest_value "arch" "${MANIFEST}")"
  if [[ "${cached_schema}" == "${CACHE_SCHEMA_VERSION}" ]] && [[ "${cached_arch}" == "${ARCH}" ]] && \
     source_fingerprint_matches "ffmpeg" "${FFMPEG_SRC}" "${MANIFEST}" && \
     source_fingerprint_matches "ffprobe" "${FFPROBE_SRC}" "${MANIFEST}" && \
     source_fingerprint_matches "comskip" "${COMSKIP_SRC}" "${MANIFEST}"; then
    echo "Using cached bundled desktop tools at ${DEST_DIR}"
    exit 0
  fi
fi

rm -rf "${DEST_DIR}"
mkdir -p "${DEST_DIR}" "${LIB_DIR}" "${STATE_DIR}"

COPIED_LIST="${STATE_DIR}/copied_libs.txt"
touch "${COPIED_LIST}"
UNRESOLVED_LIST="${STATE_DIR}/unresolved_deps.txt"
touch "${UNRESOLVED_LIST}"

copy_binary "${FFMPEG_SRC}" "ffmpeg"
copy_binary "${FFPROBE_SRC}" "ffprobe"
copy_binary "${COMSKIP_SRC}" "comskip"

copy_dep_recursive "${DEST_DIR}/ffmpeg"
copy_dep_recursive "${DEST_DIR}/ffprobe"
copy_dep_recursive "${DEST_DIR}/comskip"

patch_binary_deps "${DEST_DIR}/ffmpeg"
patch_binary_deps "${DEST_DIR}/ffprobe"
patch_binary_deps "${DEST_DIR}/comskip"

while IFS= read -r lib_file; do
  patch_library_deps "${lib_file}"
done < <(find "${LIB_DIR}" -type f -name "*.dylib" | sort)

if [[ -s "${UNRESOLVED_LIST}" ]]; then
  echo "Unresolved dependencies remain:" >&2
  sort -u "${UNRESOLVED_LIST}" >&2
  exit 1
fi

# Re-sign patched binaries/libraries so macOS does not reject modified code signatures.
while IFS= read -r sign_target; do
  codesign --force --sign - "${sign_target}" >/dev/null
done < <(
  {
    printf "%s\n" "${DEST_DIR}/ffmpeg"
    printf "%s\n" "${DEST_DIR}/ffprobe"
    printf "%s\n" "${DEST_DIR}/comskip"
    find "${LIB_DIR}" -type f -name "*.dylib" | sort
  }
)

{
  echo "schema_version=${CACHE_SCHEMA_VERSION}"
  echo "platform=darwin"
  echo "arch=${ARCH}"
  echo "generated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "ffmpeg_source=${FFMPEG_SRC}"
  echo "ffmpeg_source_mtime=$(file_mtime "${FFMPEG_SRC}")"
  echo "ffmpeg_source_size=$(file_size "${FFMPEG_SRC}")"
  echo "ffprobe_source=${FFPROBE_SRC}"
  echo "ffprobe_source_mtime=$(file_mtime "${FFPROBE_SRC}")"
  echo "ffprobe_source_size=$(file_size "${FFPROBE_SRC}")"
  echo "comskip_source=${COMSKIP_SRC}"
  echo "comskip_source_mtime=$(file_mtime "${COMSKIP_SRC}")"
  echo "comskip_source_size=$(file_size "${COMSKIP_SRC}")"
  echo
  echo "libraries:"
  find "${LIB_DIR}" -type f | sort
} > "${MANIFEST}"

echo "Bundled desktop tools created at ${DEST_DIR}"
