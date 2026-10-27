"""Normalize only alpha-equivalent public capability and wire implementations."""
import json
import re
from functools import lru_cache
from pathlib import Path

_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_$][\w$]*|[0-9]+(?:\.[0-9]+)?|[^\s]')
_IDENT = re.compile(r'[A-Za-z_$][\w$]*\Z')
_FIXED = set(('this function return var let const new null true false typeof undefined if else for while do switch case break continue try catch throw instanceof delete in void JSON String Math window pos dbf stringify parseFloat').split())

@lru_cache(maxsize=1)
def _reference():
    try:
        value=json.loads(Path(__file__).with_name('declaration_reference.json').read_text(encoding='utf-8'))
        if value.get('schema')!='ka-declaration-alpha/v1': return []
        snippets=value.get('snippets')
        if not isinstance(snippets,list) or not snippets or any(not isinstance(s,str) or not s for s in snippets):return []
        return [_TOKEN.findall(s) for s in snippets]
    except (OSError,ValueError,TypeError):
        return []


def _lex(source):
    """Keep quoted text, comments and expression-position regex literals opaque."""
    index=0;previous=None
    simple=re.compile(r'[A-Za-z_$][\w$]*|[0-9]+(?:\.[0-9]+)?|&&|\|\||[^\s]')
    while index<len(source):
        if source[index].isspace(): index+=1;continue
        start=index;char=source[index]
        if source.startswith('//',index):
            end=source.find('\n',index);index=len(source) if end<0 else end+1;continue
        if source.startswith('/*',index):
            end=source.find('*/',index+2)
            if end<0:return
            index=end+2;continue
        if char in ('"',"'",'`'):
            index+=1
            while index<len(source):
                if source[index]=='\\':index+=2;continue
                if source[index]==char:index+=1;break
                index+=1
            yield start,index,source[start:index];previous='literal';continue
        if char=='/' and (previous is None or previous in {'=', '(', '[', '{', ',', ':', ';', '!', '?', 'return', 'case', 'throw', '&&', '||'}):
            index+=1;in_class=False
            while index<len(source):
                current=source[index]
                if current=='\\':index+=2;continue
                if current=='[':in_class=True
                elif current==']':in_class=False
                elif current=='/' and not in_class:
                    index+=1
                    while index<len(source) and source[index].isalpha():index+=1
                    break
                index+=1
            yield start,index,source[start:index];previous='literal';continue
        match=simple.match(source,index)
        if not match:return
        index+=len(match[0]);previous=match[0];yield start,index,match[0]


def normalize_declaration_sources(common, client):
    """Require every literal, operator and identifier relation in all slices.

    Unknown structure returns the original sources, preserving unresolved status.
    Strings are never rewritten, including game registration and wire values.
    """
    mapping={}; reverse={}
    def role(seq,index):
        return 'member' if index and seq[index-1]=='.' or index+1<len(seq) and seq[index+1]==':' else 'symbol'
    for reference in _reference():
        pattern=[]
        for index,token in enumerate(reference):
            if _IDENT.fullmatch(token) and token not in _FIXED:
                known=mapping.get((role(reference,index),token))
                pattern.append(re.escape(known) + r'(?![\w$])' if known else r'[A-Za-z_$][\w$]*')
            else: pattern.append(re.escape(token))
        expression=r'(?<![\w$])'+r'\s*'.join(pattern)
        candidates=[]
        for match in re.finditer(expression,common):
            actual_tokens=_TOKEN.findall(match[0])
            if len(actual_tokens)!=len(reference):continue
            trial=dict(mapping);back=dict(reverse)
            for index,(expected,actual) in enumerate(zip(reference,actual_tokens)):
                if _IDENT.fullmatch(expected) and expected not in _FIXED:
                    if not _IDENT.fullmatch(actual) or actual in _FIXED:break
                    namespace=role(reference,index)
                    if namespace!=role(actual_tokens,index):break
                    key=(namespace,expected);target=(namespace,actual)
                    if key in trial and trial[key]!=actual:break
                    if target in back and back[target]!=expected:break
                    trial[key]=actual;back[target]=expected
                elif expected!=actual:break
            else:candidates.append((trial,back))
        if len(candidates)!=1:return common,client
        mapping,reverse=candidates[0]
    def normalize(source):
        matches=list(_lex(source));parts=[m[2] for m in matches];out=[];last=0
        for index,match in enumerate(matches):
            out.append(source[last:match[0]]);out.append(reverse.get((role(parts,index),match[2]),match[2]) if _IDENT.fullmatch(match[2]) else match[2]);last=match[1]
        out.append(source[last:]);return ''.join(out)
    return normalize(common),normalize(client)
