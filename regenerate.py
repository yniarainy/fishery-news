"""Regenerate newsletter from existing DB data (no re-fetch)."""
import os, sys
os.environ['DEEPSEEK_API_KEY'] = 'REDACTED_API_KEY'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from datetime import datetime

from src.config import get_config, get_prompts
from src.storage.db import Database
from src.storage.models import Issue

config = get_config()
prompts = get_prompts()
db = Database(config["storage"]["sqlite_path"])

# Get latest issue
issue_num = db.get_latest_issue_number()
if not issue_num:
    # 首次生成：计算本周编号
    from datetime import datetime
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    issue_num = f"{iso_year}-W{iso_week:02d}"
issue = db.get_issue(issue_num)
articles = db.get_articles_by_issue(issue_num)
print(f"Issue #{issue_num}: {len(articles)} articles")

# Generate editorial
from src.processors.summarizer import Summarizer
smr = Summarizer(config, prompts)
cat_dist = db.get_category_distribution(issue_num)
editorial = smr.generate_weekly_editorial(articles, [], cat_dist)
print(f"Editorial: {editorial[:80]}...")

# Generate insights
from src.processors.insights import InsightGenerator
gen = InsightGenerator(config, prompts)
insights = gen.run(articles, [], db)

# Render markdown
from src.outputs.markdown import MarkdownRenderer
renderer = MarkdownRenderer(config)
md = renderer.render(issue, articles, [], insights, editorial)

# Write markdown
out_dir = Path(config["storage"]["output_path"]) / f"issue-{issue_num}"
out_dir.mkdir(parents=True, exist_ok=True)
md_path = out_dir / "newsletter.md"
md_path.write_text(md, encoding="utf-8")
print(f"Markdown: {md_path} ({len(md)} chars)")

# Write site
from src.outputs.site import SiteGenerator
site = SiteGenerator(config)
site.generate(md, issue, articles, insights, editorial)
print(f"Site: site/issue-{issue_num}/index.html")

# Also copy to root as standalone newsletter
md_path_standalone = Path("newsletter.md")
md_path_standalone.write_text(md, encoding="utf-8")
print(f"Standalone: {md_path_standalone}")

db.close()
print("Done!")
