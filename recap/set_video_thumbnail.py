import argparse

from youtube_upload import set_video_thumbnail


def main():
    parser = argparse.ArgumentParser(description="Set a YouTube video's custom thumbnail")
    parser.add_argument("--video-id", required=True, help="YouTube video ID")
    parser.add_argument("--thumbnail", required=True, help="Path to a JPEG thumbnail")
    args = parser.parse_args()

    set_video_thumbnail(args.video_id, args.thumbnail)
    print(f"Custom thumbnail set for https://www.youtube.com/watch?v={args.video_id}")


if __name__ == "__main__":
    main()
