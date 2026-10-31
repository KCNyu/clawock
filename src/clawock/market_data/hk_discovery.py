"""Hong Kong discovery feasibility receipt: no approved redistributable feed yet."""


def collect():
    # HTTP reachability is not permission to automate a feed or redistribute it.
    # Keep this result free of vendor rows, even when a public endpoint responds.
    return {
        "schema_version": 1, "market": "HK", "status": "unavailable",
        "research_only": True, "candidates": [],
        "reason_code": "redistribution_permission_missing",
        "degraded": ["港股候选未启用：尚无已核验的自动采集与再分发授权"],
        "requirements": ["允许自动采集及公开再分发的数据源",
                         "普通股证券身份及行业覆盖", "行情观察日期及场次核验"],
        "feasibility": {
            "eastmoney": {"fields": "code, industry, turnover, market cap, quote timestamp",
                          "permission": "written permission required; not established"},
            "hkex": {"fields": "security master spreadsheet",
                     "permission": "automated collection and derivative databases restricted"},
        },
    }
