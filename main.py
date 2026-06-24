import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-update-runner":
        from app.update_runner import main as run_update_runner

        raise SystemExit(run_update_runner(sys.argv[2:]))

    from app.main_app import main as run_app

    run_app()


if __name__ == "__main__":
    main()
