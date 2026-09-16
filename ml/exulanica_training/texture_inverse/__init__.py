"""The texture inverse model: from a picture of a surface, a recipe a published maker can bake.

``export`` reads a synthetic training export and verifies it against the manifest the repository
commits. ``targets`` turns a recipe into the numbers a network predicts, from the makers' own
manifests. ``model`` and ``train`` need torch and run only in the training environment, and
``train`` refuses to start without an operator's recorded approval.
"""
