import os
import re
import logging
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, List
from collections import defaultdict

from dotenv import load_dotenv
from tmdbv3api import TMDb, TV, Episode

# Ollama integration
import subprocess
import json
OLLAMA_MODEL = "gpt-oss:20b"

# ----------------------
# Load .env variables
# ----------------------
load_dotenv()

# ----------------------
# Configure logging
# ----------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ----------------------
# Validate TMDb API key
# ----------------------
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY not found. Please set it in a .env file or environment variables.")

# ----------------------
# Check Ollama availability
# ----------------------
def check_ollama():
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
        return OLLAMA_MODEL in result.stdout
    except FileNotFoundError:
        logging.error("Ollama not found. Install from https://ollama.ai/")
        return False

if not check_ollama():
    logging.error(f"Ollama model {OLLAMA_MODEL} not available. Run: ollama pull {OLLAMA_MODEL}")
else:
    logging.info(f"Ollama ready with model: {OLLAMA_MODEL}")

# ----------------------
# Initialize TMDb client
# ----------------------
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = "en"
tv = TV()
episode_api = Episode()


# ----------------------
# AI-only episode detection
# ----------------------
# No regex patterns - using AI for everything

# Match resolution tags (optional)
res_regex = re.compile(r"(\d{3,4}p|[24]k)", re.IGNORECASE)

# Global cache for show data
show_cache: Dict[str, Dict] = {}

def get_show_info(show_name: str) -> Optional[Dict]:
    """Get show info from TMDb with caching."""
    if show_name in show_cache:
        return show_cache[show_name]
    
    try:
        results = tv.search(show_name)
        if not results:
            logging.warning(f"Show '{show_name}' not found on TMDb")
            return None
        
        show = results[0]
        show_info = {
            'id': show.id,
            'name': show.name,
            'seasons': {},
            'total_episodes': 0,
            'is_anime': False
        }
        
        # Get detailed show info to check if it's anime
        try:
            details = tv.details(show.id)
            genres = [genre['name'].lower() for genre in details.get('genres', [])]
            origin_countries = details.get('origin_country', [])
            
            # Check if it's likely anime
            show_info['is_anime'] = (
                'animation' in genres and 
                ('JP' in origin_countries or 'japan' in show.name.lower())
            )
            
            # Get season info
            for season_data in details.get('seasons', []):
                season_num = season_data.get('season_number', 0)
                if season_num > 0:  # Skip season 0 (specials)
                    episode_count = season_data.get('episode_count', 0)
                    show_info['seasons'][season_num] = episode_count
                    show_info['total_episodes'] += episode_count
                    
        except Exception as e:
            logging.warning(f"Error getting detailed info for '{show_name}': {e}")
        
        show_cache[show_name] = show_info
        logging.info(f"Cached show: {show_name} (Anime: {show_info['is_anime']}, Total episodes: {show_info['total_episodes']})")
        return show_info
        
    except Exception as e:
        logging.error(f"Error searching for show '{show_name}': {e}")
        return None

def ask_ollama_for_anime_mapping(show_info: Dict, detected_season: int, detected_episode: int) -> Optional[int]:
    """
    Use Ollama to analyze TMDb season data and determine correct continuous episode numbering for anime.
    """
    prompt = f"""You are an expert at anime episode numbering. Analyze this TMDb data for an anime show:

Show: {show_info['name']}
TMDb Season Data: {show_info['seasons']}
Total Episodes in TMDb: {show_info['total_episodes']}

The file shows: Season {detected_season} Episode {detected_episode}

TASK: Determine the correct continuous episode number for Season 1.

CONTEXT:
- Anime typically has 12-13 episodes per season (called "cours")
- TMDb often incorrectly combines multiple seasons/cours into one season
- For continuous numbering: Season 2 Episode 1 = Season 1's episode count + 1
- Most anime: Season 1 = episodes 1-12, Season 2 = episodes 13-24, etc.

CRITICAL: If TMDb shows Season 1 with 24-26 episodes, it likely combined 2 seasons worth of episodes.
In this case, use 12 episodes per season for calculation, NOT the TMDb count.

ANALYSIS:
- If Season 1 shows 12-13 episodes: Use that count
- If Season 1 shows 24-26 episodes: It's likely 2 seasons combined, use 12 per season
- For Season {detected_season} Episode {detected_episode}: Calculate as (Season-1) × 12 + Episode

What continuous episode number should Season {detected_season} Episode {detected_episode} be?

Respond with ONLY the episode number (e.g., "15" for episode 15).
If unsure, respond: UNKNOWN"""

    try:
        result = subprocess.run([
            'ollama', 'run', OLLAMA_MODEL, prompt
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logging.warning(f"Ollama error for anime mapping: {result.stderr}")
            return None
        
        response = result.stdout.strip()
        
        if response == "UNKNOWN":
            return None
        
        # Extract the last number from the response (in case there's extra text)
        import re
        numbers = re.findall(r'\b\d+\b', response)
        if numbers:
            try:
                continuous_ep = int(numbers[-1])  # Take the last number found
                if 1 <= continuous_ep <= 200:  # Reasonable range
                    logging.info(f"Ollama suggested continuous episode: {continuous_ep}")
                    return continuous_ep
                else:
                    logging.warning(f"Ollama returned unreasonable episode number: {continuous_ep}")
                    return None
            except ValueError:
                pass
        
        logging.warning(f"Ollama returned non-numeric response: {response[:100]}...")
        return None
            
    except subprocess.TimeoutExpired:
        logging.warning("Ollama timeout for anime mapping")
        return None
    except Exception as e:
        logging.warning(f"Ollama error for anime mapping: {e}")
        return None

def get_episode_title(show_name: str, season: int, episode: int) -> Optional[str]:
    """Get episode title from TMDb API."""
    show_info = get_show_info(show_name)
    if not show_info:
        return None
    
    try:
        # Get episode details using Episode API
        episode_details = episode_api.details(show_info['id'], season, episode)
        return episode_details.name if hasattr(episode_details, 'name') else None
    except Exception as e:
        logging.warning(f"Error fetching episode details for S{season:02d}E{episode:02d}: {e}")
        return None


def extract_episode_info(filename: str) -> Optional[Tuple[int, int]]:
    """
    Extract season and episode numbers using Ollama AI.
    Returns (season, episode) tuple or None if not found.
    """
    return ask_ollama_for_episode_info(filename)

def ask_ollama_for_episode_info(filename: str) -> Optional[Tuple[int, int]]:
    """
    Use Ollama to extract season/episode from filename.
    """
    prompt = f"""You are an expert at extracting season and episode numbers from video filenames. 

FILENAME: {filename}

Extract the season and episode numbers. Look for these patterns:
- S01E05, S1E5, S2E10 (season/episode format)
- 1x05, 2x10 (season x episode format)  
- E05, EP05, Episode05 (episode only - assume season 1)
- 05, 005 (just numbers - assume season 1)
- season1episode5, s1e5 (written out)

CRITICAL RULES:
1. Read numbers carefully: S01E04 = season 1 episode 4, NOT season 4 episode 4
2. If filename shows S2E15, S3E08, etc. - extract the EXACT season and episode shown
3. If only episode number found (no season), assume season 1
4. Ignore extra numbers like years (2024), resolution (1080p), or codec info
5. Focus on the main season/episode identifier in the filename

OUTPUT FORMAT: S##E## (exactly this format with zero-padded numbers)
EXAMPLES: S01EP04, S02EP15, S01EP23, S03EP01

If no season/episode pattern found, respond: NONE"""
    
    try:
        result = subprocess.run([
            'ollama', 'run', OLLAMA_MODEL, prompt
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logging.warning(f"Ollama error for '{filename}': {result.stderr}")
            return None
        
        response = result.stdout.strip()
        
        if response == "NONE":
            logging.info(f"Ollama could not parse: '{filename}'")
            return None
        
        match = re.search(r"S(\d{1,2})E(\d{1,2})", response, re.IGNORECASE)
        if match:
            season, episode = int(match.group(1)), int(match.group(2))
            # Sanity check - seasons should be 1-20, episodes 1-50
            if 1 <= season <= 20 and 1 <= episode <= 50:
                logging.info(f"Ollama extracted: S{season:02d}E{episode:02d} from '{filename}'")
                return season, episode
            else:
                logging.warning(f"Ollama returned invalid numbers S{season:02d}E{episode:02d} for '{filename}'")
                return None
        else:
            logging.warning(f"Ollama response '{response}' doesn't match expected format for '{filename}'")
            return None
            
    except subprocess.TimeoutExpired:
        logging.warning(f"Ollama timeout for '{filename}'")
        return None
    except Exception as e:
        logging.warning(f"Ollama error for '{filename}': {e}")
        return None

def detect_show_from_folder(folder_path: Path) -> Optional[str]:
    """Try to detect show name from folder name."""
    folder_name = folder_path.name
    # Clean up folder name
    show_name = re.sub(r'[_\-\.]', ' ', folder_name)
    show_name = re.sub(r'\s+', ' ', show_name).strip()
    return show_name if show_name else None

def group_files_by_show(root_path: Path) -> Dict[str, List[Path]]:
    """Group video files by show folder."""
    show_files = defaultdict(list)
    video_extensions = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm'}
    
    for file_path in root_path.rglob('*'):
        if file_path.suffix.lower() in video_extensions:
            # Find the show folder (immediate parent of video file)
            show_folder = file_path.parent
            if show_folder != root_path:  # Not in root directory
                show_name = detect_show_from_folder(show_folder)
                if show_name:
                    show_files[show_name].append(file_path)
            else:
                # Files directly in root - use filename to guess show
                filename_clean = re.sub(r'[_\-\.]', ' ', file_path.stem)
                # For files in root, try to extract show name before numbers
                # Use AI to help identify show name vs episode info
                words = filename_clean.split()
                if len(words) >= 2:
                    # Take first 2-3 words as potential show name
                    show_name = ' '.join(words[:3]).strip()
                    if show_name:
                        show_files[show_name].append(file_path)
    
    return dict(show_files)

def rename_show_files(show_name: str, files: List[Path], dry_run: bool = False, log_file_path: Optional[Path] = None):
    """Rename all files for a specific show."""
    logging.info(f"\nProcessing show: {show_name} ({len(files)} files)")
    
    # Create before/after log
    log_entries = []
    
    # Get show info to determine if continuous numbering is needed
    show_info = get_show_info(show_name)
    if not show_info:
        logging.error(f"Could not find show '{show_name}' on TMDb - skipping")
        return
    
    is_anime = show_info['is_anime']
    logging.info(f"Processing {'anime' if is_anime else 'regular TV show'}: {show_name}")
    
    for file_path in files:
        filename = file_path.name
        suffix = file_path.suffix
        
        episode_info = extract_episode_info(filename)
        if not episode_info:
            logging.warning(f"Skipping '{filename}': no episode info found")
            continue
        
        detected_season, detected_episode = episode_info
        
        # For anime, always use Season 1 with LLM-determined continuous numbering
        if is_anime:
            # Use LLM to analyze TMDb data and determine correct continuous episode number
            continuous_ep = ask_ollama_for_anime_mapping(show_info, detected_season, detected_episode)
            
            if continuous_ep:
                # LLM provided a mapping
                final_season = 1
                final_episode = continuous_ep
                logging.info(f"LLM anime mapping: S{detected_season:02d}E{detected_episode:02d} -> S01EP{continuous_ep:03d}")
            else:
                # Fallback to simple calculation (12 episodes per season)
                continuous_ep = detected_episode
                if detected_season > 1:
                    continuous_ep += (detected_season - 1) * 12
                final_season = 1
                final_episode = continuous_ep
                logging.info(f"Fallback anime mapping: S{detected_season:02d}E{detected_episode:02d} -> S01EP{continuous_ep:03d}")
        else:
            # For regular TV shows, use detected season/episode as-is
            final_season = detected_season
            final_episode = detected_episode
        
        # Get episode title with fallback for anime
        title = get_episode_title(show_name, final_season, final_episode)
        
        # If anime continuous numbering failed, try original season/episode
        if not title and is_anime and final_season == 1:
            logging.info(f"Continuous numbering failed, trying original S{detected_season:02d}EP{detected_episode:03d}")
            title = get_episode_title(show_name, detected_season, detected_episode)
            if title:
                # Use the original season/episode that worked
                final_season = detected_season
                final_episode = detected_episode
                logging.info(f"Using original season/episode for output")
            else:
                # No title found anywhere - use original season/episode for filename consistency
                final_season = detected_season
                final_episode = detected_episode
                logging.info(f"No title found, using original S{detected_season:02d}EP{detected_episode:03d} for filename")
        
        if not title:
            logging.warning(f"Title not found for S{final_season:02d}EP{final_episode:03d} - using generic")
            title = f"{final_episode}"
        
        # Clean up title for filename
        safe_title = re.sub(r'[^A-Za-z0-9\s]', '', title)
        safe_title = re.sub(r'\s+', '.', safe_title).strip('.')[:50]
        
        # Extract resolution (leave blank if not found)
        res_match = res_regex.search(filename)
        resolution = res_match.group(1).lower() if res_match else ""
        
        # Generate new filename
        clean_show_name = re.sub(r'[^A-Za-z0-9\s]', '', show_name)
        clean_show_name = re.sub(r'\s+', '.', clean_show_name)
        
        # Build filename with optional resolution (use EP format for episodes) 
        if safe_title and safe_title != str(final_episode):
            # Use episode title if available and not just the episode number
            if resolution:
                new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}.{safe_title}.{resolution}{suffix}"
            else:
                new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}.{safe_title}{suffix}"
        else:
            # No title or title is just episode number - omit it
            if resolution:
                new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}.{resolution}{suffix}"
            else:
                new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}{suffix}"
        
        logging.debug(f"Debug: show_name='{show_name}', clean_show_name='{clean_show_name}', safe_title='{safe_title}', new_name='{new_name}'")
        new_path = file_path.parent / new_name
        
        # Handle name collisions
        counter = 1
        while new_path.exists() and new_path != file_path:
            if safe_title and safe_title != str(final_episode):
                if resolution:
                    new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}.{safe_title}_{counter}.{resolution}{suffix}"
                else:
                    new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}.{safe_title}_{counter}{suffix}"
            else:
                if resolution:
                    new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}_{counter}.{resolution}{suffix}"
                else:
                    new_name = f"{clean_show_name}.S{final_season:02d}EP{final_episode:03d}_{counter}{suffix}"
            new_path = file_path.parent / new_name
            counter += 1
        
        if new_path == file_path:
            logging.info(f"Already named correctly: {filename}")
            continue
        
        log_entries.append({
            'original': filename,
            'detected': f"S{detected_season:02d}E{detected_episode:02d}",
            'final': f"S{final_season:02d}E{final_episode:02d}",
            'new_name': new_name,
            'title': title
        })
        
        logging.info(f"{'[DRY RUN] ' if dry_run else ''}Renaming: {filename} -> {new_name}")
        
        if not dry_run:
            try:
                file_path.rename(new_path)
            except Exception as e:
                logging.error(f"Failed to rename '{filename}': {e}")
    
    # Write to log file
    if log_entries and log_file_path:
        write_rename_log(log_file_path, show_name, log_entries)

def write_rename_log(log_file_path: Path, show_name: str, log_entries: List[Dict]):
    """Write rename log to file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_data = {
        'timestamp': timestamp,
        'show_name': show_name,
        'total_files': len(log_entries),
        'entries': log_entries
    }
    
    # Append to existing log file or create new one
    if log_file_path.exists():
        with open(log_file_path, 'r') as f:
            existing_data = json.load(f)
        if not isinstance(existing_data, list):
            existing_data = [existing_data]
        existing_data.append(log_data)
    else:
        existing_data = [log_data]
    
    with open(log_file_path, 'w') as f:
        json.dump(existing_data, f, indent=2)
    
    logging.info(f"Logged {len(log_entries)} renames to {log_file_path}")

def main():
    parser = argparse.ArgumentParser(description='TMDb Video Renamer - Automatically rename video files with TMDb metadata')
    parser.add_argument('path', nargs='?', default='.', help='Path to scan for video files (default: current directory)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be renamed without actually renaming')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')
    
    root_path = Path(args.path).resolve()
    if not root_path.exists():
        logging.error(f"Path does not exist: {root_path}")
        return
    
    if not root_path.is_dir():
        logging.error(f"Path is not a directory: {root_path}")
        return
    
    logging.info(f"Scanning directory: {root_path}")
    logging.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE RENAME'}")
    
    # Group files by show
    show_files = group_files_by_show(root_path)
    
    if not show_files:
        logging.warning("No video files found in any show folders")
        return
    
    logging.info(f"Found {len(show_files)} shows:")
    for show_name, files in show_files.items():
        logging.info(f"  - {show_name}: {len(files)} files")
    
    # Create log file
    log_file = root_path / f"rename_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # Process each show
    total_files = sum(len(files) for files in show_files.values())
    logging.info(f"Processing {total_files} files total with local Ollama AI")
    
    for show_name, files in show_files.items():
        rename_show_files(show_name, files, dry_run=args.dry_run, log_file_path=log_file)
    
    logging.info("\nRenaming complete!")

if __name__ == "__main__":
    main()