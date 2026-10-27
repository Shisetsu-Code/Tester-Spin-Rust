"""Describe bundled outcomes without counting animation frames as paid spins."""
from __future__ import annotations


def response_rounds(data):
    collections = []
    def visit(value, path, depth):
        if depth > 8:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = path + '/' + str(key)
                if key in {'spins', 'free_spins', 'freespins', 'rounds'} and isinstance(child, list) and child:
                    if all(isinstance(x, dict) and any(k in x for k in ('outcome', 'screen', 'win', 'round_id')) for x in child):
                        collections.append({'path':child_path, 'count':len(child), 'kind':'bundled_results'})
                visit(child, child_path, depth+1)
        elif isinstance(value, list):
            # Collections are indexed, preserving their original order in RAW.
            for index, child in enumerate(value[:256]):
                if isinstance(child, dict):
                    visit(child, path+'/'+str(index), depth+1)
    visit(data, '', 0)
    outcome = data.get('outcome')
    storage = outcome.get('storage') if isinstance(outcome, dict) else {}
    frames = storage.get('saved_screens') if isinstance(storage, dict) else None
    return {'collections':collections, 'animation_frames':len(frames) if isinstance(frames, list) else 0,
            'note':'Bundled results and animation frames are not additional paid requests.'}
