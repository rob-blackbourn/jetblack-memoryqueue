from jetblack_memoryqueue import memoryqueue


def main() -> None:
    mq = memoryqueue(b'abc')
    print(mq)
    print(mq.startswith(b'a'))


if __name__ == "__main__":
    main()
