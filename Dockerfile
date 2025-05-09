name: Docker Build (No Login)

on:
  push:
    branches: ["master"]
  pull_request:
    branches: ["master"]

jobs:
  build-and-save:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Build Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false  # Disable registry push
          tags: youtube-mp3:local-build

      - name: Save image as artifact
        run: |
          docker save youtube-mp3:local-build -o image.tar
          ls -lh image.tar  # Verify file size
        shell: bash

      - name: Upload image artifact
        uses: actions/upload-artifact@v4
        with:
          name: docker-image
          path: image.tar
          retention-days: 1
