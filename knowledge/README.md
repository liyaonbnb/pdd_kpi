# Knowledge bundle

`data/knowledge.db.gz` is a generated, read-only deployment artifact built from the unified Pinduoduo operations knowledge base.

Regenerate it from the repository root with:

```powershell
venv\Scripts\python scripts\build_knowledge_bundle.py
```

At runtime the API materializes the database into `data/knowledge/knowledge.db`, which is excluded from Git. Set `PDD_KNOWLEDGE_DB` to use a separately managed server database instead.
