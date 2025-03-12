#!/usr/bin/env python3
import browser_cookie3
import json
from playwright.sync_api import sync_playwright
from datetime import datetime
from pprint import pprint

from gcp_secret import gcp_get_secret, gcp_update_secret

ESSENTIAL_COOKIE_NAME = "checker"
TARGET_URL = "runkeeper.com"


def cookie_to_dict(cookie):
    """Converts a browser_cookie3.Cookie object to a dictionary."""
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "expires": cookie.expires,
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
    """Converts a distance string (e.g., "2.19 mi", "5 km") to miles."""
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
        print(f"No cookie consent modal found or already accepted: {str(e)}")

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
                print(f"Found essential cookie: {cookie.name}")
                if hasattr(cookie, "expires"):
                    expiry_date = datetime.fromtimestamp(cookie.expires)
                    print(f"Expires: {expiry_date}")
                return cookie_to_dict(cookie)

        print(f"Warning: Could not find essential cookie: {ESSENTIAL_COOKIE_NAME}")
        return None
    except Exception as e:
        print(f"Error getting cookies: {e}")
        return None


def format_cookie_for_playwright(cookie):
    """Format cookie for Playwright context"""
    if not cookie:
        return {}

    return {
        "name": cookie.get("name", ESSENTIAL_COOKIE_NAME),
        "value": cookie.get("value"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "expires": cookie.get("expires"),
        "sameSite": "Lax",
    }


def scrape_activities(page, user_id, months):
    """Scrape activities for a specific user"""
    activities = []
    page.goto(f"https://runkeeper.com/user/{user_id}/activitylist")
    page.wait_for_load_state("networkidle")

    for month in months:
        try:
            cur_month = f'[data-date="{month}-01-2025"]'
            month_selector = page.query_selector(cur_month)

            if not month_selector:
                print(f"No activities found for {month}")
                continue

            month_selector.click()
            page.wait_for_timeout(2000)  # Wait for content to load
            # Wait for content to load - use a more reliable approach
            page.wait_for_selector(
                'div[role="tabpanel"][aria-hidden="false"] ul', state="attached"
            )

            activity_elements = page.query_selector_all(
                'div[role="tabpanel"][aria-hidden="false"] ul > li'
            )

            if not activity_elements:
                print(f"No activities found for {month}")
                continue

            for activity in activity_elements:
                try:
                    # Extract data in a single pass
                    date_element = activity.query_selector("a span.startDate")
                    distance_element = activity.query_selector("a span.unitDistance")

                    if date_element and distance_element:
                        date_text = date_element.text_content().strip()
                        distance_text = distance_element.text_content().strip()

                        # Get activity type by getting all text and removing known parts
                        all_content = activity.text_content()
                        activity_type = (
                            all_content.replace(date_text, "")
                            .replace(distance_text, "")
                            .strip()
                        )

                        # Convert distance and add to activities
                        distance_float = convert_distance_to_float(distance_text)
                        activities.append(
                            {
                                "date": date_text + "/25",
                                "distance": distance_float,
                                "type": activity_type,
                            }
                        )
                except Exception as e:
                    print(f"Error processing activity: {e}")
                    continue

            print(f"Scraped {len(activities)} activities for {month}")

        except Exception as e:
            print(f"Error processing month {month}: {e}")
            continue

    return activities


def export_to_json(activities_data, filename="../../data.json"):
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
    print(f"Total runners: {formatted_data['metadata']['totalRunners']}")
    print(f"Total activities: {formatted_data['metadata']['totalActivities']}")


def main():
    # Try to get cookies from GCP first
    cookie = gcp_get_secret()

    # If no cookies from GCP, get from browser and update GCP
    if not cookie:
        print("Getting cookie from local browser")
        cookie = get_essential_cookie(TARGET_URL)
        if not cookie:
            print("Failed to get essential cookie. Exiting.")
            return

        # Update GCP with new cookie
        formatted_cookie = format_cookie_for_playwright(cookie)
        # gcp_update_secret(formatted_cookie)
        print("Exported cookie to GCP Secrets")
    else:
        print("Using cookie from GCP Secrets")
        formatted_cookie = format_cookie_for_playwright(cookie)
        # formatted_cookie = cookie

    all_activities = {}

    # Run everything in a single browser session
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([formatted_cookie])
        page = context.new_page()

        # Handle cookie modal once at the start
        page.goto(f"https://runkeeper.com")
        handle_cookie_modal(page)

        try:
            for user_id, name in spartans.items():
                print(f"\nScraping activities for {name} ({user_id})")
                user_activities = scrape_activities(page, user_id, months)
                all_activities[name] = user_activities
                print(f"Found {len(user_activities)} activities for {name}")
        except Exception as e:
            print(f"Error during automation: {e}")
        finally:
            browser.close()

    export_to_json(all_activities)


if __name__ == "__main__":
    spartans = {
        "3458344072": "Bruce",
        # "1703449362": "PT",
        # "499228564": "Scotch",
        # "1306204356": "Trinspiration",
        # "2522499234": "Moose",
        # "2920829518": "AutumnBreeze",
        # "2953059004": "Jon",
        # "2948464110": "Tin",
        # "2966454388": "Muscles",
        # "3338995094": "Gato",
        # "3486035198": "Alfredo",
        # KnockKnck
    }
    months = get_months_until_now()
    print(f"Scraping months: {months}")
    main()
