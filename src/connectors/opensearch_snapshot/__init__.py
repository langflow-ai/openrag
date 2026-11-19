"""OpenSearch snapshot import connector (engine + service).

Keep this module import-light: submodules are imported explicitly by callers so
that importing the package never pulls in boto3, opensearchpy or the DB layer.
"""
