import asyncio
import scanner

if __name__ == "__main__":
    try:
        asyncio.run(scanner.command_handler())
    except KeyboardInterrupt:
        pass
