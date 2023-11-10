import json
import numpy as np


def read_parameters(filename: str):
    """Read basic calculation parameters from JSON file.

    Argument:
    filename: name of the JSON file that contains the QDET output.
    """

    with open(filename, "r") as f:
        raw_ = json.load(f)

    indexmap = np.array(raw_["output"]["Q"]["indexmap"], dtype=int)

    npair = len(indexmap)
    nspin = int(raw_["system"]["electron"]["nspin"])
    bands = np.array(raw_["input"]["wfreq_control"]["qp_bands"], dtype=int)

    return nspin, npair, bands

def read_lband(bands):
    """Determine the numbers of band

    Argument:
    bands: the bands returned from read_parameters()
    """
    #length of bands list: lband
    if isinstance(bands[0],np.ndarray) and len(bands)==2: 
        #print("Band is spin resolved")
        if len(bands[0])==len(bands[1]):
            lband = len(bands[0])
        else:
            raise NotImplementedError("Different N.O orbitals from two channel case is not implemented!")
    else:
        lband = len(bands)
    return lband


def read_qp_energies(filename: str):
    """Read QP energies from JSON file.

    Argument:
    filename: name of the JSON file that contains the QDET output.
    """

    with open(filename, "r") as f:
        raw_ = json.load(f)

    nspin, npair, bands = read_parameters(filename)

    if nspin == 1:
        qp_energies = np.array(raw_["output"]["Q"]["K000001"]["eqpSec"])

    elif nspin == 2:
        qp_energies = np.zeros((read_lband(bands), 2))
        qp_energies[:, 0] = np.array(raw_["output"]["Q"]["K000001"]["eqpSec"])
        qp_energies[:, 1] = np.array(raw_["output"]["Q"]["K000002"]["eqpSec"])

    return qp_energies


def read_occupation(filename: str):
    """Read DFT occupation from JSON file.

    Argument:
    filename: name of the JSON file that contains the QDET output.
    """
    with open(filename, "r") as f:
        raw_ = json.load(f)

    nspin, npair, bands = read_parameters(filename)

    occ_ = np.zeros((nspin, read_lband(bands)))

    for ispin in range(nspin):
        string1 = "K" + format(ispin + 1, "06d")
        occ_[ispin, :] = np.array(
            raw_["output"]["Q"][string1]["occupation"], dtype=float
        )

    return occ_


def read_matrix_elements(filename: str, string: str = "eri_w"):
    """Read one-body and two-body terms from JSON file.

    Arguments:
    filename: name of the JSON file that contains the QDET output.
    string: descriptor of the two-body terms.
    """

    with open(filename, "r") as f:
        raw_ = json.load(f)

    nspin, npair, bands = read_parameters(filename)

    indexmap = np.array(raw_["output"]["Q"]["indexmap"], dtype=int)

    # allocate one- and two-body terms in basis of pairs of KS states
    eri_pair = np.zeros((nspin, nspin, npair, npair))
    h1e_pair = np.zeros((nspin, npair))

    # read one-body terms from file
    for ispin in range(nspin):
        string1 = "K" + format(ispin + 1, "06d")
        h1e_pair[ispin, :] = np.array(raw_["qdet"]["h1e"][string1], dtype=float)

    # read two-body terms from file
    for ispin1 in range(nspin):
        string1 = "K" + format(ispin1 + 1, "06d")
        for ispin2 in range(nspin):
            string2 = "K" + format(ispin2 + 1, "06d")

            for ipair in range(npair):
                string3 = "pair" + format(ipair + 1, "06d")
                eri_pair[ispin1, ispin2, ipair, :] = np.array(
                    raw_["qdet"][string][string1][string2][string3], dtype=float
                )

    # unfold one-body terms from pair basis to Kohn-Sham basis

    h1e = np.zeros((nspin, read_lband(bands), read_lband(bands)))
    for ispin in range(nspin):
        for ipair in range(len(indexmap)):
            i, j = indexmap[ipair]
            h1e[ispin, i - 1, j - 1] = h1e_pair[ispin, ipair]
            h1e[ispin, j - 1, i - 1] = h1e_pair[ispin, ipair]

    # unfold two-body terms from pair to Kohn-Sham basis
    eri = np.zeros(
        (
            nspin,
            nspin,
            read_lband(bands),
            read_lband(bands),
            read_lband(bands),
            read_lband(bands),
        )
    )
    for ispin in range(nspin):
        for jspin in range(nspin):
            for ipair in range(len(indexmap)):
                i, j = indexmap[ipair]
                for jpair in range(len(indexmap)):
                    k, l = indexmap[jpair]
                    eri[ispin, jspin, i - 1, j - 1, k - 1, l - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
                    eri[ispin, jspin, i - 1, j - 1, l - 1, k - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
                    eri[ispin, jspin, j - 1, i - 1, k - 1, l - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
                    eri[ispin, jspin, j - 1, i - 1, l - 1, k - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]

                    eri[jspin, ispin, k - 1, l - 1, i - 1, j - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
                    eri[jspin, ispin, k - 1, l - 1, j - 1, i - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
                    eri[jspin, ispin, l - 1, k - 1, i - 1, j - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
                    eri[jspin, ispin, l - 1, k - 1, j - 1, i - 1] = eri_pair[
                        ispin, jspin, ipair, jpair
                    ]
    return h1e, eri


def read_overlap(filename: str):
    """Read overlap between spin up and spin down orbitals from JSON file.

    Argument:
    filename: name of the JSON file that contains the QDET output.
    """
    with open(filename, "r") as f:
        raw_ = json.load(f)

    overlap = np.array(raw_["qdet"]["overlap_ab"], dtype=float)
    n = int(np.sqrt(overlap.shape[0]))
    assert n**2 == overlap.shape[0], "The size of the overlap matrix is wrong"
    overlap = np.reshape(overlap, (n, n)).T

    return overlap
