"""Reader-facing provenance for the London-gold reference series."""

XAU_PRIMARY_SOURCE = 'sina_global_futures_xau'
XAU_FALLBACK_SOURCE = 'eastmoney_gc00y_fallback'


def history_summary(london):
    """Use fetch provenance and retained rows, including portfolios written by older versions."""
    provenance = london.get('hist_source') or {}
    source = provenance.get('name')
    if source == XAU_FALLBACK_SOURCE and provenance.get('points') == 0:
        source = 'unavailable'  # Older refreshes could label an empty fallback as a source.
    if source == XAU_PRIMARY_SOURCE:
        summary = '伦敦金历史 · 新浪现货'
    elif source == XAU_FALLBACK_SOURCE:
        summary = '伦敦金历史使用 COMEX 期货补位'
    elif source == 'not_attempted':
        summary = '伦敦金历史本轮未刷新'
    elif source == 'unavailable':
        summary = ('伦敦金历史沿用上次数据' if london.get('hist_series')
                   else '伦敦金历史暂无可用参考点')
    else:
        summary = ''

    if (london.get('fx_hist_source') or {}).get('points') == 0:
        fx_summary = ('美元兑人民币历史沿用上次数据' if london.get('fx_hist_series')
                      else '美元兑人民币历史暂无可用参考点')
        return ' · '.join(filter(None, (summary, fx_summary)))
    return summary
