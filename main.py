import praw
import numpy as np
import math
import os
from datetime import datetime, timedelta
from supabase import create_client, Client

# Reddit API credentials from environment variables
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Supabase credentials from environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# Data Fetcher: Fetch top posts from Reddit's front page
def fetch_data():
    print("Fetching data from Reddit...")
    for submission in reddit.front.hot(limit=10):
        if submission.is_self:
            continue  # Skip self-posts
        
        post_data = {
            "post_id": submission.id,
            "title": submission.title,
            "linked_page_title": submission.link_title if hasattr(submission, 'link_title') else '',
            "upvotes": submission.score,
            "comments_count": submission.num_comments,
            "timestamp": datetime.utcfromtimestamp(submission.created_utc).isoformat(),
            "fetch_time": datetime.utcnow().isoformat(),
            "score": None 
        }

        # Insert or upsert data into Supabase
        response = supabase.table("posts").upsert(post_data).execute()
        if response.get("status_code") != 200:
            print(f"Failed to upsert post: {submission.id}")
        else:
            print(f"Upserted post: {submission.id}")

def analyze_data():
    print("Analyzing data...")
    current_time = datetime.utcnow()
    time_window = current_time - timedelta(hours=24) 
    
    # Fetch posts from the last 24 hours
    response = supabase.table("posts").select("post_id, upvotes, comments_count, timestamp").gte("fetch_time", time_window.isoformat()).execute()
    data = response.get("data", [])
    
    if not data:
        print("No data available for analysis.")
        return

    upvotes = [d["upvotes"] for d in data]
    comments = [d["comments_count"] for d in data]
    post_ages = [(current_time - datetime.fromisoformat(d["timestamp"])).total_seconds() / 60.0 for d in data]  # Age in minutes
    
    mean_upvotes = np.mean(upvotes)
    std_dev_upvotes = np.std(upvotes)

    # Normalization of current data (Min-Max)
    u_min, u_max = min(upvotes), max(upvotes)
    c_min, c_max = min(comments), max(comments)
    
    for post in data:
        post_id = post["post_id"]
        u_norm = (post["upvotes"] - u_min) / (u_max - u_min) if (u_max - u_min) > 0 else 0
        c_norm = (post["comments_count"] - c_min) / (c_max - c_min) if (c_max - c_min) > 0 else 0
        
        age = (current_time - datetime.fromisoformat(post["timestamp"])).total_seconds() / 60.0
        decay = math.exp(-0.01 * age)  # Decay constant k = 0.01
        
        # Final scoring
        w1, w2 = 0.7, 0.3  # Weights for upvotes and comments
        score = (w1 * u_norm + w2 * c_norm) * decay
        
        response = supabase.table("posts").update({"score": score}).eq("post_id", post_id).execute()
        if response.get("status_code") != 200:
            print(f"Failed to update score for post ID: {post_id}")
        print(f"Updated score for post ID: {post_id} - Score: {score}")

if __name__ == "__main__":
    fetch_data()
    analyze_data()
