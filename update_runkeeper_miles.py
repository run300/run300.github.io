#!/usr/bin/env python3
import browser_cookie3
import json
from playwright.sync_api import sync_playwright
from datetime import datetime
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'  # ✓
    RED = '\033[91m'    # ✗
    YELLOW = '\033[93m' # ⚠️
    BLUE = '\033[94m'   # →
    PURPLE = '\033[95m' # 🏃
    CYAN = '\033[96m'   # 📊
    WHITE = '\033[97m'  # Regular text
    BOLD = '\033[1m'    # Bold
    END = '\033[0m'     # Reset

# Colored symbols
CHECK = f"{Colors.GREEN}✓{Colors.END}"
CROSS = f"{Colors.RED}✗{Colors.END}"
WARNING = f"{Colors.YELLOW}⚠️{Colors.END}"
ARROW = f"{Colors.BLUE}→{Colors.END}"
RUNNER = f"{Colors.PURPLE}🏃{Colors.END}"
CHART = f"{Colors.CYAN}📊{Colors.END}"

# from gcp_secret import gcp_get_secret  # Unused in current implementation

ESSENTIAL_COOKIE_NAME = "checker"
TARGET_URL = "runkeeper.com"
TRACKED_ACTIVITIES = ["running", "hiking", "walking", "trail running"]

# Configuration for concurrent scraping
MAX_WORKERS = 2  # Number of concurrent browser sessions (2 users at a time)
HEADLESS_MODE = True  # Set to False for debugging (shows browser windows)

# Performance notes:
# - Higher MAX_WORKERS = faster scraping but more resource usage
# - Recommended: 2-4 workers for most systems
# - Each worker runs its own browser instance


def cookie_to_dict(cookie):
    """Converts a browser_cookie3.Cookie object to a dictionary."""
    # Handle invalid expiry dates
    expires = cookie.expires
    if expires and (expires < 0 or expires > 2147483647):  # Unix timestamp range check
        expires = None
    
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "expires": expires,
        "secure": cookie.secure,
        "version": cookie.version,
        "port": cookie.port,
        "domain_initial_dot": cookie.domain_initial_dot,
        "path_specified": cookie.path_specified,
        "domain_specified": cookie.domain_specified,
        "discard": cookie.discard,
        "comment": cookie.comment,
        "comment_url": cookie.comment_url,
        "rfc2109": cookie.rfc2109,
    }


def convert_distance_to_float(distance_string):
    """Converts a distance string (e.g., "2.19 mi", "5 km") to miles int/float."""
    if not distance_string:
        return None

    try:
        value, unit = distance_string.split()
        value = float(value)

        if unit.lower() == "mi":
            return value
        elif unit.lower() == "km":
            return value * 0.621371
        else:
            print(f"Unknown unit: {distance_string}")
            return None
    except ValueError:
        return None


def normalize_date(date_text, month_part, year_part):
    """Normalize date to mm/dd/yy format using month context."""
    try:
        # If date already has slashes, it might be in mm/dd format
        if "/" in date_text:
            parts = date_text.split("/")
            if len(parts) == 2:
                month_num, day = parts
                # Use the year from the month context
                year_short = year_part[-2:]  # Get last 2 digits of year
                return f"{month_num.zfill(2)}/{day.zfill(2)}/{year_short}"
        
        # If date is in format like "Jan 15" or "15"
        if " " in date_text:
            # Format like "Jan 15" - extract just the day
            day = date_text.split()[-1]
        else:
            # Format like "15" - just the day
            day = date_text
        
        # Convert month abbreviation to number
        month_abbrev = month_part
        month_map = {
            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
        }
        
        month_num = month_map.get(month_abbrev, '01')
        year_short = year_part[-2:]  # Get last 2 digits of year
        
        return f"{month_num}/{day.zfill(2)}/{year_short}"
        
    except Exception as e:
        print(f"    {WARNING} Error normalizing date '{date_text}': {e}")
        # Fallback to original date with year
        return f"{date_text}/{year_part[-2:]}"


def get_months_until_now():
    """Returns a list of abbreviated month names from January until the current month."""
    current = datetime.now()
    return [
        datetime(2025, month, 1).strftime("%b") for month in range(1, current.month + 1)
    ]


def handle_cookie_modal(page, timeout=5000):
    """Handle cookie consent modal if it appears on the page."""
    try:
        # Check for cookie banner
        if page.wait_for_selector("#onetrust-banner-sdk", timeout=timeout):
            # Look for accept button and click if found
            accept_button = page.wait_for_selector(
                "#onetrust-accept-btn-handler", state="visible", timeout=timeout
            )
            if accept_button:
                accept_button.click()
                print("Cookie consent accepted")
                # Wait for any animations/transitions to complete
                page.wait_for_load_state("networkidle", timeout=timeout)
                return True
    except Exception as e:
        print(f"{WARNING} No cookie consent modal found or already accepted: {str(e)}")

    return False


def get_essential_cookie(url, browser="firefox"):
    """Get only the essential cookie from the browser"""
    try:
        cookie_jar = (
            browser_cookie3.firefox(domain_name=url)
            if browser.lower() == "firefox"
            else browser_cookie3.chrome(domain_name=url)
        )

        # Find the essential cookie
        for cookie in cookie_jar:
            if cookie.name == ESSENTIAL_COOKIE_NAME:
                print(f"{CHECK} Found essential cookie: {cookie.name}")
                if hasattr(cookie, "expires") and cookie.expires:
                    try:
                        expiry_date = datetime.fromtimestamp(cookie.expires)
                        print(f"{CHECK} Expires: {expiry_date}")
                    except (ValueError, OSError) as e:
                        print(f"{WARNING} Invalid expiry date: {e}")
                return cookie_to_dict(cookie)

        print(f"{WARNING} Warning: Could not find essential cookie: {ESSENTIAL_COOKIE_NAME}")
        return None
    except Exception as e:
        print(f"{CROSS} Error getting cookies: {e}")
        return None


def format_cookie_for_playwright(cookie):
    """Format cookie for Playwright context"""
    if not cookie:
        return {}

    # Handle expires - Playwright expects a number or None
    expires = cookie.get("expires")
    if expires is None or expires == 0:
        expires = -1  # Session cookie

    return {
        "name": cookie.get("name", ESSENTIAL_COOKIE_NAME),
        "value": cookie.get("value"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "expires": expires,
        "sameSite": "Lax",
    }


def scrape_activities(page, user_id, months, user_name=None):
    """Scrape activities for a specific user"""
    activities = []
    name_prefix = f"[{user_name}] " if user_name else ""

    try:
        print(f"{name_prefix}{ARROW} Navigating to user activity list...")
        page.goto(f"https://runkeeper.com/user/{user_id}/activitylist")
        page.wait_for_load_state("networkidle")
        print(f"{name_prefix}{CHECK} Successfully loaded user activity page")
    except Exception as e:
        print(f"{name_prefix}{CROSS} Error navigating to user page: {e}")
        return activities

    for month in months:
        try:
            print(f"{name_prefix}Processing month: {month}")
            cur_month = f'[data-date="{month}-01-2025"]'

            try:
                print(f"{name_prefix}  {ARROW} Looking for month selector: {cur_month}")
                month_selector = page.wait_for_selector(cur_month, timeout=5000)
                if not month_selector:
                    print(f"{name_prefix}  {CROSS} No month selector found for {month}")
                    continue
                print(f"{name_prefix}  {CHECK} Found month selector for {month}")
            except Exception as e:
                print(f"{name_prefix}  {CROSS} Error finding month selector for {month}: {e}")
                continue

            print(f"{name_prefix}  {ARROW} Clicking month {month}...")
            month_selector.click()
            page.wait_for_timeout(2000)
            print(f"{name_prefix}  {CHECK} Clicked month {month}")

            # Wait for content to load with better error handling
            try:
                print(f"{name_prefix}  {ARROW} Waiting for activity list to load...")
                # Wait for network activity to complete
                page.wait_for_load_state("networkidle", timeout=10000)
                
                # Wait for the activity list to be visible
                page.wait_for_selector(
                    'div[role="tabpanel"][aria-hidden="false"] ul',
                    state="attached",
                    timeout=10000,
                )
                print(f"{name_prefix}  {CHECK} Activity list loaded for {month}")
            except Exception as e:
                print(f"{name_prefix}  {CROSS} Error loading activity list for {month}: {e}")
                continue

            # Get fresh references to activities each time
            try:
                # Try multiple selectors for activities
                activity_selectors = [
                    'div[role="tabpanel"][aria-hidden="false"] ul > li',
                    'div[role="tabpanel"] ul > li',
                    '.activity-list li',
                    'ul.activity-list li',
                    'li.activity-item'
                ]
                
                monthly_activities = []
                for selector in activity_selectors:
                    monthly_activities = page.query_selector_all(selector)
                    if monthly_activities:
                        print(f"{name_prefix}{CHECK} Found activities using selector: {selector}")
                        break
                
                # If still no activities, try scrolling to load more
                if not monthly_activities:
                    print(f"{name_prefix}{WARNING} No activities found with standard selectors for {month}, trying scroll...")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2000)
                    monthly_activities = page.query_selector_all('div[role="tabpanel"][aria-hidden="false"] ul > li')
                
                # Try to load more activities if there's a "Load More" button
                if monthly_activities:
                    try:
                        load_more_selectors = [
                            'button:has-text("Load More")',
                            'a:has-text("Load More")',
                            'button:has-text("Show More")',
                            'a:has-text("Show More")',
                            '.load-more',
                            '.show-more'
                        ]
                        
                        for load_selector in load_more_selectors:
                            try:
                                load_more_button = page.wait_for_selector(load_selector, timeout=2000)
                                if load_more_button and load_more_button.is_visible():
                                    print(f"{name_prefix}{CHECK} Found load more button: {load_selector}")
                                    load_more_button.click()
                                    page.wait_for_timeout(3000)
                                    # Get updated activities after loading more
                                    monthly_activities = page.query_selector_all('div[role="tabpanel"][aria-hidden="false"] ul > li')
                                    print(f"{name_prefix}{CHECK} After loading more: {len(monthly_activities)} activities")
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        print(f"{name_prefix}{CROSS} Error trying to load more activities: {e}")

                if not monthly_activities:
                    print(f"{name_prefix}{CROSS} No activities found for {month}")
                    continue

                print(f"{name_prefix}  {CHECK} Found {len(monthly_activities)} activities for {month}")
                
                # Additional wait to ensure all activities are loaded
                page.wait_for_timeout(2000)

                # Process each activity one at a time to avoid stale element issues
                print(f"{name_prefix}  {ARROW} Starting to process {len(monthly_activities)} activities...")
                for i in range(len(monthly_activities)):
                    try:
                        print(f"{name_prefix}    [{i + 1}/{len(monthly_activities)}] {ARROW} Processing activity...")
                        
                        # Get fresh activity list each time to avoid stale elements
                        current_activities = page.query_selector_all(
                            'div[role="tabpanel"][aria-hidden="false"] ul > li'
                        )
                        
                        if i >= len(current_activities):
                            print(f"{name_prefix}    {CROSS} No more activities found, stopping at {i}")
                            break
                            
                        activity = current_activities[i]

                        # Get fresh selectors for each activity to avoid stale references
                        date_element = activity.query_selector("a span.startDate")
                        distance_element = activity.query_selector(
                            "a span.unitDistance"
                        )

                        if not date_element or not distance_element:
                            print(f"{name_prefix}    {CROSS} Missing date or distance element for activity {i + 1}")
                            continue

                        # Extract text content before clicking
                        date_text = date_element.text_content().strip()
                        distance_text = distance_element.text_content().strip()

                        # Get activity type by getting all text and removing known parts
                        all_content = activity.text_content()
                        activity_type = (
                            all_content.replace(date_text, "")
                            .replace(distance_text, "")
                            .strip()
                        )
                        
                        # Get the month from the current month selector to normalize the date
                        month_year = cur_month.split('"')[1]  # Extract "Jan-01-2025" from '[data-date="Jan-01-2025"]'
                        month_part = month_year.split('-')[0]  # Extract "Jan"
                        year_part = month_year.split('-')[2]  # Extract "2025"
                        
                        # Debug: Print what we found
                        print(f"{name_prefix}    {ARROW} Found: {date_text}, {distance_text}, {activity_type}")
                        print(f"{name_prefix}    {ARROW} Month context: {month_part} {year_part}")

                        # Open activity in new tab to get detailed information
                        try:
                            # Get the activity URL first
                            activity_link = activity.query_selector("a")
                            if not activity_link:
                                print(f"{name_prefix}{CROSS} No activity link found for activity {i + 1}")
                                continue
                            
                            # Get the href attribute
                            activity_url = activity_link.get_attribute("href")
                            if not activity_url:
                                print(f"{name_prefix}{CROSS} No URL found for activity {i + 1}")
                                continue
                            
                            # Make sure it's a full URL
                            if activity_url.startswith("/"):
                                activity_url = f"https://runkeeper.com{activity_url}"
                            
                            print(f"{name_prefix}    {ARROW} Opening activity in new tab...")
                            
                            # Small delay to avoid overwhelming the browser
                            page.wait_for_timeout(500)
                            
                            # Open new tab
                            new_page = page.context.new_page()
                            
                            try:
                                # Navigate to the activity page
                                print(f"{name_prefix}    {ARROW} Loading activity details...")
                                new_page.goto(activity_url)
                                new_page.wait_for_load_state("networkidle", timeout=10000)

                                # Get duration and pace with error handling
                                duration_text = "N/A"
                                average_pace_text = "N/A"

                                try:
                                    duration_element = new_page.wait_for_selector(
                                        "#totalDuration > h1 > span", timeout=5000
                                    )
                                    if duration_element:
                                        duration_text = duration_element.inner_text()
                                except Exception:
                                    print("Could not find duration element")

                                try:
                                    pace_element = new_page.wait_for_selector(
                                        "#averagePace > h1 > span", timeout=5000
                                    )
                                    if pace_element:
                                        average_pace_text = pace_element.inner_text()
                                except Exception:
                                    print("Could not find pace element")

                                # Convert distance and add to activities
                                distance_float = convert_distance_to_float(distance_text)
                                
                                # Normalize date to mm/dd/yy format using month context
                                formatted_date = normalize_date(date_text, month_part, year_part)
                                print(f"{name_prefix}    {ARROW} Normalized date: {date_text} → {formatted_date}")
                                
                                activity_data = {
                                    "date": formatted_date,
                                    "distance": distance_float,
                                    "type": activity_type,
                                    "duration": duration_text,
                                    "pace": average_pace_text,
                                }
                                activities.append(activity_data)
                                print(f"{name_prefix}    {CHECK} Added activity: {formatted_date} - {distance_float}mi - {duration_text} - {average_pace_text}")

                            finally:
                                # Always close the new tab
                                print(f"{name_prefix}    {ARROW} Closing activity tab...")
                                new_page.close()

                        except Exception as e:
                            print(f"{name_prefix}    {CROSS} Error getting detailed info for activity {i + 1}: {e}")
                            # Make sure to close any open tabs
                            try:
                                if 'new_page' in locals():
                                    new_page.close()
                            except Exception:
                                pass
                            continue

                    except Exception as e:
                        print(f"{name_prefix}    {CROSS} Error processing activity {i + 1}: {e}")
                        continue

                monthly_count = len([a for a in activities if month.lower() in a.get('date', '').lower()])
                print(f"{name_prefix}  {CHECK} Completed {month}: {monthly_count} activities scraped")

            except Exception as e:
                print(f"{name_prefix}  {CROSS} Error getting activities for month {month}: {e}")
                continue

        except Exception as e:
            print(f"{name_prefix}  {CROSS} Error processing month {month}: {e}")
            continue

    print(f"{name_prefix}  {CHECK} Finished scraping all months. Total activities: {len(activities)}")
    return activities


def export_to_json(activities_data, filename="data.json"):
    """Export activities data to a JSON file"""
    # Calculate some useful statistics while formatting the data
    formatted_data = {
        "runners": {},
        "metadata": {
            "lastUpdated": datetime.now().isoformat(),
            "totalRunners": len(activities_data),
            "totalActivities": sum(
                len(activities) for activities in activities_data.values()
            ),
        },
    }

    for runner, activities in activities_data.items():
        # Calculate runner statistics
        total_distance = sum(act["distance"] for act in activities if act["distance"])
        activity_types = set(act["type"] for act in activities)

        formatted_data["runners"][runner] = {
            "name": runner,
            "stats": {
                "totalActivities": len(activities),
                "totalDistance": round(total_distance, 2),
                "activityTypes": list(activity_types),
            },
            "activities": sorted(activities, key=lambda x: x["date"]),
        }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(formatted_data, f, indent=2, ensure_ascii=False)

    pprint(formatted_data)
    print(f"{CHART} Total runners: {formatted_data['metadata']['totalRunners']}")
    print(f"{CHART} Total activities: {formatted_data['metadata']['totalActivities']}")


def scrape_user_activities(user_id, name, months, cookie):
    """Scrape activities for a single user in their own browser session"""
    thread_id = threading.current_thread().name
    print(f"\n{RUNNER} [Thread-{thread_id}] Starting scraping for {name} ({user_id})")
    
    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=HEADLESS_MODE)
            context = browser.new_context()
            context.add_cookies([cookie])
            page = context.new_page()

            # Handle cookie modal
            page.goto("https://runkeeper.com")
            handle_cookie_modal(page)

            # Scrape activities for this user
            user_activities = scrape_activities(page, user_id, months, name)
            print(f"{CHECK} [Thread-{thread_id}] Completed {name}: {len(user_activities)} activities found")
            
            browser.close()
            return name, user_activities
            
    except Exception as e:
        print(f"{CROSS} [Thread-{thread_id}] Error scraping {name}: {e}")
        return name, []


def main():
    start_time = time.time()
    
    # Get cookies from local browser for testing
    print("Getting cookie from local browser")
    cookie = get_essential_cookie(TARGET_URL)
    if not cookie:
        print("Failed to get essential cookie. Exiting.")
        return

    formatted_cookie = format_cookie_for_playwright(cookie)
    print("Using cookie from local browser")

    all_activities = {}
    
    # Configure concurrent scraping
    print(f"{RUNNER} Starting concurrent scraping with {MAX_WORKERS} workers")
    print(f"{WARNING} Headless mode: {HEADLESS_MODE}")
    print(f"{CHART} Users to process: {len(spartans)}")
    
    # Use ThreadPoolExecutor for concurrent scraping
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all scraping tasks
        future_to_user = {
            executor.submit(scrape_user_activities, user_id, name, months, formatted_cookie): (user_id, name)
            for user_id, name in spartans.items()
        }
        
        # Collect results as they complete
        completed_count = 0
        for future in as_completed(future_to_user):
            user_id, name = future_to_user[future]
            try:
                name, user_activities = future.result()
                all_activities[name] = user_activities
                completed_count += 1
                elapsed = time.time() - start_time
                print(f"{CHART} [{completed_count}/{len(spartans)}] Collected data for {name}: {len(user_activities)} activities (Elapsed: {elapsed:.1f}s)")
            except Exception as e:
                print(f"{CROSS} Error processing {name}: {e}")
                all_activities[name] = []

    total_time = time.time() - start_time
    print(f"\n{CHECK} Concurrent scraping completed!")
    print(f"{WARNING} Total time: {total_time:.1f} seconds")
    print(f"{CHART} Total users processed: {len(all_activities)}")
    print(f"{CHART} Total activities collected: {sum(len(activities) for activities in all_activities.values())}")
    print(f"{WARNING} Average time per user: {total_time/len(spartans):.1f} seconds")
    
    export_to_json(all_activities)


if __name__ == "__main__":
    spartans = {
        "3458344072": "Bruce",
        "1703449362": "PT",
        "499228564": "Scotch",
        "1306204356": "Trinspiration",
        "2522499234": "Moose",
        "2920829518": "AutumnBreeze",
        "2953059004": "Jon",
        "2948464110": "Tin",
        "2966454388": "Muscles",
        # "3338995094": "Gato",
        "3486035198": "Alfredo",
        # KnockKnck
    }
    months = get_months_until_now()
    print(f"{ARROW} Scraping months: {months}")
    
    # Start timing the entire script execution
    script_start_time = time.time()
    print(f"{RUNNER} Script execution started at {time.strftime('%H:%M:%S')}")
    print("=" * 60)
    
    main()
    
    # Calculate and print total execution time
    script_total_time = time.time() - script_start_time
    print("=" * 60)
    print(f"{CHECK} SCRIPT EXECUTION COMPLETED!")
    print(f"{WARNING} Total execution time: {script_total_time:.1f} seconds ({script_total_time/60:.1f} minutes)")
    print(f"{CHART} Finished at: {time.strftime('%H:%M:%S')}")
    print("=" * 60)
