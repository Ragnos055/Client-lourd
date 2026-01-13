from typing import Dict, List, Tuple

from reedsolo import RSCodec


def encode_to_shards(data: bytes, data_shards: int, total_shards: int) -> Tuple[List[bytes], int]:
    """
    Segmente `data` en `data_shards` fragments logiques et calcule des fragments
    de parité supplémentaires pour obtenir `total_shards` fragments au total.

    Retourne (liste_des_shards, pad_len), où pad_len est le nombre d'octets de
    padding ajouté à la fin de `data` pour obtenir un multiple de data_shards.
    """
    if total_shards <= 0 or data_shards <= 0:
        raise ValueError("data_shards et total_shards doivent être > 0")
    if total_shards <= data_shards:
        raise ValueError("total_shards doit être > data_shards pour Reed-Solomon")

    parity = total_shards - data_shards
    rsc = RSCodec(parity)

    # padding pour que la longueur soit multiple de data_shards
    pad_len = (-len(data)) % data_shards
    if pad_len:
        data += b"\x00" * pad_len

    shards = [bytearray() for _ in range(total_shards)]

    # On traite data en blocs de data_shards octets.
    for i in range(0, len(data), data_shards):
        block = data[i : i + data_shards]
        # codeword = data_shards données + parity octets de parité = total_shards
        codeword = rsc.encode(block)
        for idx in range(total_shards):
            shards[idx].append(codeword[idx])

    return [bytes(b) for b in shards], pad_len


def decode_from_shards(
    shards: Dict[int, bytes], data_shards: int, total_shards: int, pad_len: int
) -> bytes:
    """
    Reconstruit les données originales à partir d'un sous-ensemble de shards.

    - shards: dict {index_shard: données_shard}, avec au moins data_shards entrées.
    - data_shards, total_shards, pad_len doivent correspondre aux paramètres
      utilisés lors de l'encodage.
    """
    if len(shards) < data_shards:
        raise ValueError("Nombre de shards insuffisant pour la reconstruction")

    parity = total_shards - data_shards
    rsc = RSCodec(parity)

    # Tous les shards doivent avoir la même longueur en octets
    any_shard = next(iter(shards.values()))
    shard_len = len(any_shard)

    out = bytearray()

    # Pour chaque position (colonne) dans les shards, on reconstitue le codeword
    # complet (total_shards octets) avec effacement pour les shards manquants.
    for pos in range(shard_len):
        codeword = bytearray(total_shards)
        erasures = []
        for idx in range(total_shards):
            if idx in shards:
                codeword[idx] = shards[idx][pos]
            else:
                codeword[idx] = 0
                erasures.append(idx)

        decoded, _, _ = rsc.decode(bytes(codeword), erase_pos=erasures)
        # decoded contient les data_shards octets d'origine pour cette "ligne"
        out.extend(decoded)

    if pad_len:
        return bytes(out[:-pad_len])
    return bytes(out)

