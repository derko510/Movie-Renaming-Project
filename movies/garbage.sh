#!/bin/bash

# Define episode counts per season
declare -A got_season_eps=([1]=10 [2]=10 [3]=10 [4]=10 [5]=10 [6]=10 [7]=7 [8]=6)
declare -A ram_season_eps=([1]=11 [2]=10 [3]=10 [4]=10 [5]=10 [6]=10 [7]=10)
declare -A sl_season_eps=([1]=12 [2]=12)

function random_garbage() {
  local junk=(
    "1080p" "720P" "webRip" "x264" "x265" "YIFY" "RARBG"
    "BluRay" "HDRip" "HEVC" "AAC" "5.1CH" "10bit" "HMAX"
    "EngSub" "NF" "PSA" "DSNP" "IMMERSE" "eztv"
  )
  echo -n "${junk[RANDOM % ${#junk[@]}]}"
}

function random_name_garble() {
  local base="$1"
  base="${base// /}"  # Remove spaces
  base=$(echo "$base" | tr '[:upper:]' '[:lower:]')
  [ $((RANDOM % 2)) -eq 0 ] && base=$(echo "$base" | sed 's/a/@/g')
  [ $((RANDOM % 2)) -eq 0 ] && base=$(echo "$base" | sed 's/o/0/g')
  echo "$base"
}

function create_files() {
  local show="$1"
  local folder="$2"
  declare -n seasons="$3"

  mkdir -p "$folder"

  for season in "${!seasons[@]}"; do
    for ((ep=1; ep<=seasons[$season]; ep++)); do
      s=$(printf "%02d" "$season")
      e=$(printf "%02d" "$ep")
      base="${show} S${s}E${e}"
      garbled=$(random_name_garble "$base")
      suffix=$(random_garbage)
      delimiter=$([ $((RANDOM % 2)) -eq 0 ] && echo "." || echo "-")
      filename="${garbled}${delimiter}${suffix}.mkv"
      echo "Creating: $folder/$filename"
      touch "$folder/$filename"
    done
  done
}

create_files "Game.of.Thrones" "Game_of_Thrones" got_season_eps
create_files "Rick.and.Morty" "Rick_and_Morty" ram_season_eps
create_files "Solo.Leveling" "Solo_Leveling" sl_season_eps
