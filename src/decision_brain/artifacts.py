"""JSON/NPZ serialization: inference never unpickles an artifact."""
import json
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler


def export_encoder(enc,path):
    vec=enc['vectorizer'];scale=enc['scaler']
    value={'numeric':enc['numeric'],'text':enc['text'],'vectorizer':None,'scaler':None}
    if vec is not None:
        value['vectorizer']={'vocabulary':{k:int(v) for k,v in vec.vocabulary_.items()},'idf':vec.idf_.tolist()}
    if scale is not None:
        value['scaler']={'mean':scale.mean_.tolist(),'scale':scale.scale_.tolist(),'var':scale.var_.tolist(),
                         'samples':int(scale.n_samples_seen_)}
    path.write_text(json.dumps(value,ensure_ascii=False), encoding='utf-8')


def import_encoder(path):
    value=json.loads(path.read_text(encoding='utf-8'));vec=None;scale=None
    if value['vectorizer'] is not None:
        v=value['vectorizer'];vec=TfidfVectorizer(vocabulary=v['vocabulary'],ngram_range=(1,2),sublinear_tf=True,strip_accents='unicode')
        vec.idf_=np.asarray(v['idf'],dtype=np.float64)
    if value['scaler'] is not None:
        s=value['scaler'];scale=StandardScaler()
        scale.mean_=np.asarray(s['mean']);scale.scale_=np.asarray(s['scale']);scale.var_=np.asarray(s['var'])
        scale.n_features_in_=len(s['mean']);scale.n_samples_seen_=s['samples']
    return {'numeric':value['numeric'],'text':value['text'],'vectorizer':vec,'scaler':scale}
