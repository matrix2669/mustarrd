#!/usr/bin/env bash

# Resolve and export ffmpeg/ffprobe/comskip runtime paths for terminal workflows.
# Intended to be sourced from scripts/dev.sh and scripts/oneapp.sh.

catchup_is_executable() {
  local file_path="${1:-}"
  [[ -n "$file_path" && -x "$file_path" ]]
}

catchup_prepend_path_entries() {
  local current_path="${1:-}"
  shift || true

  local entry
  local merged=()
  local current_parts=()

  for entry in "$@"; do
    [[ -n "$entry" ]] || continue
    merged+=("$entry")
  done

  if [[ -n "$current_path" ]]; then
    IFS=':' read -r -a current_parts <<< "$current_path"
  fi
  for entry in "${current_parts[@]-}"; do
    [[ -n "$entry" ]] || continue
    merged+=("$entry")
  done

  local deduped=()
  local seen=""
  for entry in "${merged[@]-}"; do
    if [[ ":$seen:" != *":$entry:"* ]]; then
      deduped+=("$entry")
      seen+="$entry:"
    fi
  done

  (IFS=':'; echo "${deduped[*]}")
}

catchup_resolve_first_executable() {
  local candidate
  for candidate in "$@"; do
    if catchup_is_executable "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

catchup_tool_executable_name() {
  local tool_name="$1"
  if [[ "${CATCHUP_TOOL_PLATFORM:-}" == "win32" ]]; then
    echo "${tool_name}.exe"
  else
    echo "$tool_name"
  fi
}

catchup_platform_id() {
  local uname_out
  uname_out="$(uname -s 2>/dev/null || echo unknown)"
  case "$uname_out" in
    Darwin) echo "darwin" ;;
    Linux) echo "linux" ;;
    MINGW*|MSYS*|CYGWIN*) echo "win32" ;;
    *) echo "${uname_out,,}" ;;
  esac
}

catchup_arch_id() {
  local arch_out
  arch_out="$(uname -m 2>/dev/null || echo unknown)"
  case "$arch_out" in
    x86_64|amd64) echo "x64" ;;
    arm64|aarch64) echo "arm64" ;;
    *) echo "$arch_out" ;;
  esac
}

catchup_resolve_bundled_tool_path() {
  local tools_root="$1"
  local tool_name="$2"
  local executable
  executable="$(catchup_tool_executable_name "$tool_name")"

  local platform arch
  platform="${CATCHUP_TOOL_PLATFORM:-$(catchup_platform_id)}"
  arch="${CATCHUP_TOOL_ARCH:-$(catchup_arch_id)}"

  local candidate
  for candidate in \
    "$tools_root/${platform}-${arch}/$executable" \
    "$tools_root/$platform/$executable" \
    "$tools_root/$executable"; do
    if catchup_is_executable "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

catchup_collect_bundled_library_dirs() {
  local tools_root="$1"
  local platform arch
  platform="${CATCHUP_TOOL_PLATFORM:-$(catchup_platform_id)}"
  arch="${CATCHUP_TOOL_ARCH:-$(catchup_arch_id)}"

  local search_dirs=(
    "$tools_root/${platform}-${arch}"
    "$tools_root/$platform"
    "$tools_root"
  )

  local d
  for d in "${search_dirs[@]}"; do
    [[ -d "$d" ]] && echo "$d"
    [[ -d "$d/lib" ]] && echo "$d/lib"
  done
}

catchup_apply_terminal_tool_env() {
  local repo_root="$1"
  local tools_root="$repo_root/tools"

  if [[ ! -d "$tools_root" ]]; then
    return 0
  fi

  local platform
  platform="${CATCHUP_TOOL_PLATFORM:-$(catchup_platform_id)}"

  local ffmpeg_path="${CATCHUP_FFMPEG_PATH:-}"
  local ffprobe_path="${CATCHUP_FFPROBE_PATH:-}"
  local comskip_path="${CATCHUP_COMSKIP_PATH:-}"

  if [[ -z "$ffmpeg_path" ]]; then
    ffmpeg_path="$(catchup_resolve_bundled_tool_path "$tools_root" ffmpeg || true)"
  fi
  if [[ -z "$ffprobe_path" ]]; then
    ffprobe_path="$(catchup_resolve_bundled_tool_path "$tools_root" ffprobe || true)"
  fi
  if [[ -z "$comskip_path" ]]; then
    comskip_path="$(catchup_resolve_bundled_tool_path "$tools_root" comskip || true)"
  fi

  if [[ "$platform" == "darwin" ]]; then
    if [[ -z "$ffmpeg_path" ]]; then
      ffmpeg_path="$(catchup_resolve_first_executable \
        /opt/homebrew/bin/ffmpeg \
        /usr/local/bin/ffmpeg \
        /usr/bin/ffmpeg || true)"
    fi
    if [[ -z "$ffprobe_path" ]]; then
      ffprobe_path="$(catchup_resolve_first_executable \
        /opt/homebrew/bin/ffprobe \
        /usr/local/bin/ffprobe \
        /usr/bin/ffprobe || true)"
    fi
    if [[ -z "$comskip_path" ]]; then
      comskip_path="$(catchup_resolve_first_executable \
        /opt/homebrew/bin/comskip \
        /usr/local/bin/comskip \
        /usr/bin/comskip || true)"
    fi
  fi

  if [[ -n "$ffmpeg_path" ]]; then
    export CATCHUP_FFMPEG_PATH="$ffmpeg_path"
  fi
  if [[ -n "$ffprobe_path" ]]; then
    export CATCHUP_FFPROBE_PATH="$ffprobe_path"
  fi
  if [[ -n "$comskip_path" ]]; then
    export CATCHUP_COMSKIP_PATH="$comskip_path"
  fi

  local lib_dirs=()
  local dir_line
  while IFS= read -r dir_line; do
    [[ -n "$dir_line" ]] || continue
    lib_dirs+=("$dir_line")
  done < <(catchup_collect_bundled_library_dirs "$tools_root")
  if [[ "${#lib_dirs[@]}" -gt 0 ]]; then
    export PATH="$(catchup_prepend_path_entries "${PATH:-}" "${lib_dirs[@]}")"
    if [[ "$platform" == "darwin" ]]; then
      export DYLD_LIBRARY_PATH="$(catchup_prepend_path_entries "${DYLD_LIBRARY_PATH:-}" "${lib_dirs[@]}")"
    elif [[ "$platform" == "linux" ]]; then
      export LD_LIBRARY_PATH="$(catchup_prepend_path_entries "${LD_LIBRARY_PATH:-}" "${lib_dirs[@]}")"
    fi
  fi
}
