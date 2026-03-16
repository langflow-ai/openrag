import logging
from importlib import resources as impresources
from pathlib import Path

from ragworkbench.boards.board_generator import BoardGenerator
from ragworkbench.datasets_loader import ait_qa_data_loader

from openrag_eval import boards as boards_package
from openrag_eval.logging_config import init_logger
from openrag_eval.pipelines import inference as openrag_inference_module
from openrag_eval.pipelines import ingest as openrag_ingest_module
from openrag_eval.utils import load_env_file

logger = logging.getLogger(__name__)


def main() -> None:
    init_logger()

    # Load environment variables from .env file
    load_env_file()

    boards_directory = impresources.files(boards_package)

    board = BoardGenerator(board_path=Path(str(boards_directory / "table_rich")))
    board.process()

    logger.info(f"Output written to '{board.output_path}'")


if __name__ == "__main__":
    main()

# Made with Bob
