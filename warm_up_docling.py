from docling.document_converter import DocumentConverter

print('Warming up docling models...')

try:
    # Use the sample document to warm up docling
    test_file = "/app/2506.08231v1.pdf"
    print(f'Using {test_file} to warm up docling...')
    DocumentConverter().convert(test_file)
    print('Docling models warmed up successfully')
except Exception as e:
    print(f'Docling warm-up completed with: {e}')
    # This is expected - we just want to trigger the model downloads