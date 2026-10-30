"""Production entry point for the current community bot."""

if __name__ == "__main__":
    from bot_release import build_info
    build=build_info()
    if not build.get('verified'):
        changed=', '.join(build.get('changed_files',[])) or 'manifest missing or invalid'
        raise SystemExit('Release files do not match: '+changed+'. Complete the GitHub update before restarting; saved data was not changed.')
    from community_bot import run
    run()
