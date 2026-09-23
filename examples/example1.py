from jetblack_memoryqueue import memoryqueue


def main() -> None:
    mq = memoryqueue(b'abc')
    print(mq)


if __name__ == "__main__":
    main()
