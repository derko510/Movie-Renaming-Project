#!/bin/bash

# Real season/episode counts
# declare -A got_season_eps=([1]=10 [2]=10 [3]=10 [4]=10 [5]=10 [6]=10 [7]=7 [8]=6)
# declare -A ram_season_eps=([1]=11 [2]=10 [3]=10 [4]=10 [5]=10 [6]=10 [7]=10)
declare -A sl_season_eps=([2]=13)

EP_TOTAL=5

random_garbage() {
  local junk=(
    "1080p" "720P" "webRip" "x264" "x265" "YIFY" "RARBG"
    "BluRay" "HDRip" "HEVC" "AAC" "5.1CH" "10bit" "HMAX"
    "EngSub" "NF" "PSA" "DSNP" "IMMERSE" "eztv"
  )
  echo -n "${junk[RANDOM % ${#junk[@]}]}"
}

random_name_garble() {
  local base="$1"
  base="${base// /}"  # Remove spaces
  base=$(echo "$base" | tr '[:upper:]' '[:lower:]')
  [ $((RANDOM % 2)) -eq 0 ] && base=$(echo "$base" | sed 's/a/@/g')
  [ $((RANDOM % 2)) -eq 0 ] && base=$(echo "$base" | sed 's/o/0/g')
  echo "$base"
}

# Shuffle an array passed by name; result printed line-by-line
shuffle_array() {
  local -n arr_ref="$1"
  local i tmp size=${#arr_ref[@]}
  local idxs=($(seq 0 $((size-1))))
  for ((i=size-1; i>0; i--)); do
    j=$((RANDOM % (i+1)))
    tmp=${idxs[i]}
    idxs[i]=${idxs[j]}
    idxs[j]=$tmp
  done
  for i in "${idxs[@]}"; do
    echo "${arr_ref[i]}"
  done
}

create_files_distinct_seasons() {
  local show="$1"
  local folder="$2"
  declare -n seasons="$3"

  mkdir -p "$folder"

  # Collect available seasons
  local season_keys=()
  for s in "${!seasons[@]}"; do season_keys+=("$s"); done

  # Shuffle and pick as many unique seasons as possible (up to EP_TOTAL)
  mapfile -t shuffled < <(shuffle_array season_keys)
  local max_unique=$(( ${#season_keys[@]} < EP_TOTAL ? \
                       ${#season_keys[@]} : EP_TOTAL ))

  # Track used season-episode pairs to avoid duplicates
  declare -A used=()

  local made=0

  # First pass: one episode in each distinct season
  for ((i=0; i<max_unique && made<EP_TOTAL; i++)); do
    local season="${shuffled[i]}"
    local ep=$((1 + RANDOM % seasons[$season]))
    local key="${season}-${ep}"
    used["$key"]=1

    local s=$(printf "%02d" "$season")
    local e=$(printf "%02d" "$ep")
    local base="${show} S${s}E${e}"
    local garbled
    garbled=$(random_name_garble "$base")
    local suffix
    suffix=$(random_garbage)
    local delimiter=$([ $((RANDOM % 2)) -eq 0 ] && echo "." || echo "-")
    local filename="${garbled}${delimiter}${suffix}.mkv"
    echo "Creating: $folder/$filename"
    touch "$folder/$filename"
    ((made++))
  done

  # If fewer seasons than EP_TOTAL, fill remaining without repeating (s, e)
  while (( made < EP_TOTAL )); do
    local season="${season_keys[ RANDOM % ${#season_keys[@]} ]}"
    local ep=$((1 + RANDOM % seasons[$season]))
    local key="${season}-${ep}"

    # Avoid duplicate exact pair
    if [[ -n "${used[$key]}" ]]; then
      continue
    fi
    used["$key"]=1

    local s=$(printf "%02d" "$season")
    local e=$(printf "%02d" "$ep")
    local base="${show} S${s}E${e}"
    local garbled
    garbled=$(random_name_garble "$base")
    local suffix
    suffix=$(random_garbage)
    local delimiter=$([ $((RANDOM % 2)) -eq 0 ] && echo "." || echo "-")
    local filename="${garbled}${delimiter}${suffix}.mkv"
    echo "Creating: $folder/$filename"
    touch "$folder/$filename"
    ((made++))
  done
}

create_files_distinct_seasons "Game.of.Thrones" "Game_of_Thrones" got_season_eps
create_files_distinct_seasons "Rick.and.Morty" "Rick_and_Morty" ram_season_eps
create_files_distinct_seasons "Solo.Leveling" "Solo_Leveling" sl_season_eps
