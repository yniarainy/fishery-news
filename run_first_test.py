#!/usr/bin/env python
"""
首次运行测试 — 验证 DeepSeek V4 API + 采集 + LLM 处理全链路
"""
import os, sys
os.environ['DEEPSEEK_API_KEY'] = 'REDACTED_API_KEY'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI

print("=" * 50)
print("1. 测试 DeepSeek V4 模型连接...")
print("=" * 50)

client = OpenAI(
    api_key=os.environ['DEEPSEEK_API_KEY'],
    base_url='https://api.deepseek.com',
)

# Test v4-pro
try:
    r = client.chat.completions.create(
        model='deepseek-v4-pro',
        messages=[{'role': 'user', 'content': '用一句话介绍全球渔业现状（中文，15字以内）'}],
        max_tokens=30,
    )
    print(f"✅ deepseek-v4-pro: {r.choices[0].message.content}")
except Exception as e:
    print(f"❌ deepseek-v4-pro: {e}")

# Test v4-flash
try:
    r = client.chat.completions.create(
        model='deepseek-v4-flash',
        messages=[{'role': 'user', 'content': 'say: fish'}],
        max_tokens=5,
    )
    print(f"✅ deepseek-v4-flash: OK (response: {r.choices[0].message.content})")
except Exception as e:
    print(f"❌ deepseek-v4-flash: {e}")

print()
print("=" * 50)
print("2. 测试 RSS 采集...")
print("=" * 50)

from src.collectors.rss import RSSCollector

feeds = [
    ("Undercurrent News", "https://www.undercurrentnews.com/feed"),
    ("Nature Fisheries", "https://www.nature.com/subjects/fisheries.rss"),
]

working_feeds = []
for name, url in feeds:
    c = RSSCollector({
        'id': name.lower().replace(' ', '-'),
        'name': name, 'type': 'rss', 'url': url,
        'category': 'test', 'language': 'en',
        'max_articles': 5,
        'user_agent': 'Mozilla/5.0 (compatible; FisheryNewsBot/0.1)',
    })
    result = c.collect()
    if result.success and result.articles:
        print(f"✅ {name}: {len(result.articles)} articles")
        for a in result.articles[:2]:
            print(f"   📰 {a.title[:70]}")
        working_feeds.append((name, result.articles))
    else:
        print(f"❌ {name}: {result.error}")

print()
print("=" * 50)
print("3. 测试 LLM 处理流水线...")
print("=" * 50)

if working_feeds:
    # 取第一批文章做测试
    all_articles = []
    for name, articles in working_feeds:
        all_articles.extend(articles)

    print(f"共采集 {len(all_articles)} 篇文章，开始处理...")

    # 预过滤
    from src.processors.prefilter import Prefilter
    import yaml
    with open('config/settings.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    # 替换 API key
    import re
    raw_config = open('config/settings.yaml', encoding='utf-8').read()
    for env_var in ["DEEPSEEK_API_KEY", "WECHAT_APP_ID", "WECHAT_APP_SECRET",
                    "NOTION_API_KEY", "NOTION_DATABASE_ID"]:
        val = os.getenv(env_var, "")
        raw_config = raw_config.replace(f"${{{env_var}}}", val)
    config = yaml.safe_load(raw_config)

    pref = Prefilter(config)
    filtered = pref.run(all_articles)
    print(f"  Pre-filter: {len(all_articles)} → {len(filtered)}")

    # 分类
    with open('config/prompts.yaml', encoding='utf-8') as f:
        prompts = yaml.safe_load(f)

    from src.processors.classifier import Classifier
    from src.storage.db import Database
    from src.storage.vector import VectorStore

    db = Database(config['storage']['sqlite_path'])
    vector_store = VectorStore(config['storage']['chroma_path'])

    # 保存文章到 DB
    from src.storage.models import Article as DBArticle
    for a in filtered:
        db_art = DBArticle(
            id=a.compute_id(),
            source_id=a.source_id,
            source_name=a.source_name,
            url=a.url,
            title=a.title,
            raw_summary=a.raw_summary,
            published_at=a.published_at,
            language=a.language,
        )
        db.insert_article(db_art)

    clf = Classifier(config, prompts)
    classified = clf.run(filtered, db)
    cats = {}
    for a in classified:
        cat = getattr(a, '_cached_category', 'other')
        cats[cat] = cats.get(cat, 0) + 1
    print(f"  Classify: {cats}")

    # 摘要（只测 2 篇）
    from src.processors.summarizer import Summarizer
    test_articles = filtered[:2]
    smr = Summarizer(config, prompts)
    smr._summarize_single(test_articles, db)
    for a in test_articles:
        summary = getattr(a, '_cached_summary', '')
        print(f"  Summary [{a.source_name}]: {summary[:80]}...")

    # 标签
    from src.processors.tagger import Tagger
    tagger = Tagger(config, prompts)
    tagged = tagger.run(test_articles, db)
    for a in tagged:
        tags = getattr(a, '_cached_tags', [])
        entities = getattr(a, '_cached_entities', {})
        print(f"  Tags [{a.source_name}]: tags={tags}, species={entities.get('species', [])}")

    db.close()
    print()
    print("✅ 全链路测试通过！")
else:
    print("❌ 没有可用信源，跳过处理测试")

print()
print("=" * 50)
print("完成！运行完整周刊: python src/main.py --mode weekly")
print("=" * 50)
