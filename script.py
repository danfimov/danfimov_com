import markdown


with open('src/content/posts/django_admin.md', 'r') as f:
    text = f.read()
    print(markdown.markdown(text))
