"""Use the same evidence-backed counts as the grid for filtering."""
from tester_spin.feature_summary import feature_table_counts

FILTERS={'Todos':'all','Con compras':'purchase','Con antebets':'ante','Con compras o antebets':'either','Con compras y antebets':'both'}


def matches_features(result,mode='all'):
    if mode=='all':return True
    purchases,antes=feature_table_counts(result)
    buy=purchases is not None and purchases>0
    ante=antes is not None and antes>0
    return {'purchase':buy,'ante':ante,'either':buy or ante,'both':buy and ante}.get(mode,False)
