import argparse
import signal
import threading

from app import create_app
from training_control_plane import dispatch_once, run_scheduler_forever


def build_parser():
    parser = argparse.ArgumentParser(
        description='Run the ToolIbV2 durable training scheduler.',
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run one probe/dispatch tick and exit.',
    )
    parser.add_argument(
        '--interval',
        type=float,
        default=None,
        help='Override scheduler interval in seconds.',
    )
    return parser


def main():
    args = build_parser().parse_args()
    overrides = {}
    if args.interval is not None:
        if args.interval < 0.5:
            raise SystemExit('--interval must be at least 0.5 seconds.')
        overrides['TRAINING_SCHEDULER_INTERVAL_SECONDS'] = args.interval

    app = create_app(config_overrides=overrides)
    if args.once:
        result = dispatch_once(app, asynchronous=False)
        print(result)
        return

    stop_event = threading.Event()

    def stop_scheduler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, stop_scheduler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, stop_scheduler)

    app.logger.info('Training scheduler started.')
    run_scheduler_forever(app, stop_event=stop_event)
    app.logger.info('Training scheduler stopped.')


if __name__ == '__main__':
    main()
