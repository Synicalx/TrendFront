import praw
import numpy as np
import math
import os
import time
import schedule
import logging
from flask import Flask
from datetime import datetime, timedelta, UTC
from supabase import create_client, Client
from concurrent.futures import ThreadPoolExecutor
from typing import List

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                    AppleWebKit/537.36 (KHTML, like Gecko) \
                    Chrome/91.0.4472.124 Safari/537.36"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

app = Flask(__name__)

@app.route('/health')
def health_check():
    return {"status": "healthy"}, 200

def process_submission(submission) -> dict:
    """
    Process a single submission
    
    args:
        submission: A Reddit submission object

    return:
        A dictionary containing post data
    """
    if submission.is_self or not submission.url:
        return None
        
    ratio = submission.score / submission.num_comments \
            if submission.num_comments > 0 else 0
    
    return {
        "post_id": submission.id,
        "title": submission.title,
        "linked_page_title": submission.url_title if hasattr(submission, 'url_title') else submission.title,
        "linked_page_url": submission.url,
        "subreddit_name": submission.subreddit.display_name,
        "upvotes": submission.score,
        "comments_count": submission.num_comments,
        "upvote_to_comment_ratio": ratio,
        "timestamp": datetime.fromtimestamp(submission.created_utc, UTC).isoformat(),
        "fetch_time": datetime.now(UTC).isoformat(),
        "score": None
    }

def fetch_data():
    """
    Fetch data from Reddit and batch insert into Supabase database.
    """
    logging.info("Fetching data from Reddit...")
    start_time = time.time()
    
    submissions = list(reddit.front.hot(limit=10))
    posts_data: List[dict] = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(process_submission, submissions)
        posts_data = [r for r in results if r is not None]
    
    # Batch upsert to Supabase?
    if posts_data:
        supabase.table("posts").upsert(posts_data).execute()
    
    logging.info(f"Processed {len(posts_data)} posts in \
                {time.time() - start_time:.2f} seconds")

def retrieve_last_24h_posts():
    """
    Retrieve posts from the last 24 hours from the database NOT from reddit.

    return: 
        data: List of dictionaries containing post data
        current_time: Current time in UTC
    """
    logging.info("Retrieving DB data from the last 24 hours...")

    current_time = datetime.now(UTC)
    time_window = current_time - timedelta(hours=24)

    # Fetch posts from the last 24 hours
    response = supabase.table("posts") \
        .select("post_id, upvotes, comments_count, timestamp") \
        .gte("fetch_time", time_window.isoformat()) \
        .execute()

    if not response.data:
        logging.warning("No data available for analysis.")
        return
    
    return response.data, current_time

def analyze_data(data, current_time):
    """
    Analyze the data we have in DB and update the scores in the DB.

    args:
        data: List of dictionaries containing post data
        current_time: Current time in UTC
    """
    logging.info("Analyzing data...")

    try:
        upvotes = [d["upvotes"] for d in data]
        comments = [d["comments_count"] for d in data]

        post_ages = []
        for d in data:
            timestamp = datetime.fromisoformat(d["timestamp"])
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            age = (current_time - timestamp).total_seconds() / 3600.0
            post_ages.append(age)

        # Basic statistics
        mean_upvotes = np.mean(upvotes)
        std_dev_upvotes = np.std(upvotes)
        
        # Normalization of current data (Min-Max)
        u_min, u_max = min(upvotes), max(upvotes)
        c_min, c_max = min(comments), max(comments)
        
        # Prevent division by zero
        upvote_range = u_max - u_min if u_max != u_min else 1
        comment_range = c_max - c_min if c_max != c_min else 1
        
        # Calculate normalized scores
        for i, post_id in enumerate(d["post_id"] for d in data):
            norm_upvotes = (upvotes[i] - u_min) / upvote_range
            norm_comments = (comments[i] - c_min) / comment_range
            age_factor = math.exp(-post_ages[i] / 24)  # Decay factor based on age
            
            # Combined score (weighted average of normalized metrics)
            score = (0.7 * norm_upvotes + 0.3 * norm_comments) * age_factor
            
            supabase.table("posts") \
                .update({"score": float(score)}) \
                .eq("post_id", post_id) \
                .execute()
        
        logging.info(f"Analysis complete. Processed {len(data)} posts.")
        
    except Exception as e:
        logging.error(f"Error during analysis: {str(e)}")

def hourly_analysis():
    logging.info(f"Running hourly analysis at {datetime.now(UTC)}")
    try:
        data, current_time = retrieve_last_24h_posts()
        analyze_data(data, current_time)
    except Exception as e:
        logging.error(f"Error in hourly analysis: {e}")

def ten_min_fetch():
    logging.info(f"Fetching data at {datetime.now(UTC)}")
    try:
        fetch_data()
    except Exception as e:
        logging.error(f"Error in data fetch: {e}")

def run_scheduler():
    # Schedule jobs
    schedule.every(10).minutes.do(ten_min_fetch)
    schedule.every().hour.at(":00").do(hourly_analysis)
    
    logging.info("Scheduler started...")
    
    # Run initial fetch
    ten_min_fetch()
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logging.error(f"Error in scheduler: {e}")
            time.sleep(60)  # Wait a minute before retrying

def run_flask():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    run_flask()
    run_scheduler()
