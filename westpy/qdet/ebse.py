import numpy as np
import json

from pyscf.fci.cistring import make_strings, num_strings
from pyscf.fci.spin_op import spin_square
from pyscf.fci.addons import transform_ci_for_orbital_rotation

from westpy.qdet.json_parser import read_parameters, read_occupation, read_matrix_elements, read_qp_energies


class eBSE:
    def __init__(self, filename, spin_flip_=False):

        self.filename = filename
        # read QDET active space from file
        self.basis = __read_parameters(self.filename)[2]
        # read QP energies and occupation from file
        self.qp_energies = __read_qp_energies(self.filename)
        self.occ = __read_occupation(self.filename)

        # TODO: add assert to make sure that all dimensions are correct
        # make global arrays
        # TODO: add assert to make sure that occupations don't violate Aufbau
        # principle
        self.v = __read_matrix_elements(self.filename, string="v_c")
        self.w = __read_matrix_elements(self.filename, string="eri_w_full")

        self.spin_flip = spin_flip_

        # check number of dimensions of matrix elements to see whether
        # spin-polarized DFT calculation was employed or not
        # TODO: check for right number of dimension and shape
        if self.v.ndim == 4:
            self.spin_pol = False
        elif self.v.ndim == 6:
            self.spin_pol = True

        # get size of single-particle space
        self.n_orbitals = self.basis.shape[0]
        # get number of electrons
        self.n_elec = [int(np.sum(occ_[0])), int(np.sum(occ_[1]))]

        # create mapping between transitions and single-particle indices
        self.smap = self.get_smap()
        self.n_tr = self.smap.shape[0]

        # create mapping between transitions and FCI vectors
        self.cmap, self.jwstring = self.get_map_transitions_to_cistrings()

        # initialize eigenvalues and eigenvectors to None
        self.eigvals = None
        self.eigvecs = None

    def get_smap(self):
        # maps from a transition index s to the KS indices
        # (v, c, s) = smap[s]

        smap_ = []

        if not self.spin_flip:
            # loop over spin
            for m in range(2):
                # loop over occupied states
                for v in range(self.occ.shape[1]):
                    if self.occ[m][v] == 1.0:
                        # loop over conduction states
                        for c in range(self.occ.shape[1]):
                            if self.occ[m][c] == 0.0:
                                smap_.append([v, c, m])
        else:
            # for spin-flip BSE only transitions from spin-up to spin-down are
            # considered
            # loop over occupied states
            for v in range(self.occ.shape[1]):
                if self.occ[0][v] == 1.0:
                    # loop over conduction states
                    for c in range(self.occ.shape[1]):
                        if self.occ[1][c] == 0.0:
                            smap_.append([v, c, 0])

        return np.asarray(smap_)

    def solve(self):
        # solve embedded BSE, return eigenvalues and -vectors

        # allocate BSE Hamiltonian
        bse_hamiltonian = np.zeros((self.n_tr, self.n_tr))

        # add diagonal term
        for s in range(self.n_tr):
            v, c, m = self.smap[s][:]
            if not self.spin_flip:
                if self.spin_pol:
                    bse_hamiltonian[s, s] += self.qp_energy[c, m] - self.qp_energy[v, m]
                else:
                    bse_hamiltonian[s, s] += self.qp_energy[c] - self.qp_energy[v]
            else:
                m_prime = 1 - m
                if self.spin_pol:
                    bse_hamiltonian[s, s] += (
                        self.qp_energy[c, m_prime] - self.qp_energy[v, m]
                    )
                else:
                    bse_hamiltonian[s, s] += self.qp_energy[c] - self.qp_energy[v]

            # add direct and exchange terms
            for s2 in range(self.n_tr):
                v2, c2, m2 = self.smap[s2][:]
                # -------------------------------
                # spin-conserving BSE calculation
                # -------------------------------
                if not self.spin_flip:
                    if m == m2:
                        if self.spin_pol:
                            bse_hamiltonian[s, s2] += (
                                self.v[m, m, v, c, v2, c2] - self.w[m, m, v, v2, c, c2]
                            )
                        else:
                            bse_hamiltonian[s, s2] += (
                                self.v[v, c, v2, c2] - self.w[v, v2, c, c2]
                            )
                    else:
                        if self.spin_pol:
                            bse_hamiltonian[s, s2] += self.v[m, m2, v, c, v2, c2]
                        else:
                            bse_hamiltonian[s, s2] += self.v[v, c, v2, c2]
                # -------------------------------
                # spin-flip BSE calculation
                # -------------------------------
                elif self.spin_flip:
                    if m == m2:
                        if self.spin_pol:
                            bse_hamiltonian[s, s2] += -self.w[m, 1 - m, v, v2, c, c2]
                        else:
                            bse_hamiltonian[s, s2] += -self.w[v, v2, c, c2]

        # diagonalize Hamiltonian
        self.eigvals = np.linalg.eigh(bse_hamiltonian)[0]
        self.eigvecs = np.linalg.eigh(bse_hamiltonian)[1]

    def get_cistring(self, s):
        # determine cistring for the up- and down-component of a given
        # transition
        v, c, m = self.smap[s][:]
        # adjust occupation for a given transition
        occ_ = np.copy(self.occ)

        if not self.spin_flip:
            occ_[m, v] = 0.0
            occ_[m, c] = 1.0
        else:
            occ_[m, v] = 0.0
            occ_[1 - m, c] = 1.0

        # turn occupation to binary number
        cistring_ = []
        for m in range(2):
            binary = 0
            for i in range(occ_.shape[1]):
                binary += occ_[m, i] * 2**i
            cistring_.append(binary)

        return np.asarray(cistring_)

    def get_map_transitions_to_cistrings(self):
        # returns a map that associates each transition s of the transition
        # space to a pair of fci-vector indices in pyscf.fci
        # additionally: stores Jordan-Wigner string for each product of up- and
        # down-Slater determinant

        # generate all possible cistrings
        if not self.spin_flip:
            cistring_ = [
                make_strings(range(self.n_orbitals), self.n_elec[0]),
                make_strings(range(self.n_orbitals), self.n_elec[1]),
            ]
        else:
            cistring_ = [
                make_strings(range(self.n_orbitals), self.n_elec[0] - 1),
                make_strings(range(self.n_orbitals), self.n_elec[1] + 1),
            ]

        # allocate map
        cmap_ = np.zeros((self.n_tr, 2), dtype=int)

        # allocate Jordan-Wigner strings
        jwstring_ = np.zeros(self.n_tr, dtype=int)

        # loop over all transitions
        for s in range(self.n_tr):
            # determine cistrings for transition
            transition_strings = self.get_cistring(s)

            # loop over spin
            for m in range(2):
                # loop over cistrings
                for i in range(cistring_[m].shape[0]):
                    if cistring_[m][i] == transition_strings[m]:
                        cmap_[s, m] = i
            # definition is in my notes
            # TODO: put derivation in repo so it does not get lost...
            if self.spin_flip:
                jwstring_[s] = (-1) ** (self.n_elec[1] + self.smap[s][0])
            else:
                m = self.smap[s][-1]
                jwstring_[s] = (-1) ** (self.n_elec[m] + self.smap[s][0] - 1)

        return cmap_, jwstring_

    def transform_transition_to_fci(self, i):
        # TODO: ensure that the length of the eigenvector is self.n_tr
        # returns BSE eigenvector in the format of a FCI vector in pyscf.fci

        vector_ = self.eigvecs[:, i]
        # allocate FCI vector in the size of the correct Fock space
        if not self.spin_flip:
            fci_ = np.zeros(
                (
                    num_strings(self.n_orbitals, self.n_elec[0]),
                    num_strings(self.n_orbitals, self.n_elec[1]),
                )
            )
        else:
            fci_ = np.zeros(
                (
                    num_strings(self.n_orbitals, self.n_elec[0] - 1),
                    num_strings(self.n_orbitals, self.n_elec[1] + 1),
                )
            )

        # loop over all transitions
        for s in range(vector_.shape[0]):
            # find the indices of the corresponding FCI vectors
            c1 = self.cmap[s, 0]
            c2 = self.cmap[s, 1]

            # assign value
            fci_[c1, c2] = vector_[s] * self.jwstring[s]

        return fci_

    def get_spin(self, i):
        # return the total spin and multiplicity for BSE eigenstate
        fci_ = self.transform_transition_to_fci(i)

        # account for different occupation in excited state in spin-flip BSE
        if not self.spin_flip:
            nelec_ = self.n_elec
        else:
            nelec_ = (self.n_elec[0] - 1, self.n_elec[1] + 1)

        return spin_square(fci_, self.n_orbitals, nelec_)

    def _pretty_binary_print(self, binary):
        return format(binary, "0" + str(self.n_orbitals) + "b")

    def get_transition_information(self, i, cutoff=10 ** (-3)):
        # returns a string that displays the excited state vector as a linear
        # combination of Fock vectors

        vector_ = self.eigvecs[:, i]

        # get all possible FCI strings
        if not self.spin_flip:
            cistring_ = [
                make_strings(range(self.n_orbitals), self.n_elec[0]),
                make_strings(range(self.n_orbitals), self.n_elec[1]),
            ]
        else:
            cistring_ = [
                make_strings(range(self.n_orbitals), self.n_elec[0] - 1),
                make_strings(range(self.n_orbitals), self.n_elec[1] + 1),
            ]
        # output string
        str_ = ""
        # get string and contribution for each component of the BSE eigenvector
        for s in range(vector_.shape[0]):
            if abs(vector_[s]) >= cutoff:
                s1 = self.cmap[s, 0]
                s2 = self.cmap[s, 1]
                string_fock1 = (
                    "|"
                    + format(cistring_[0][s1], "0" + str(self.n_orbitals) + "b")
                    + ">"
                )
                string_fock2 = (
                    "|"
                    + format(cistring_[1][s2], "0" + str(self.n_orbitals) + "b")
                    + ">"
                )
                str_ += (
                    format(vector_[s] * self.jwstring[s], "+4.3f")
                    + ""
                    + string_fock1
                    + string_fock2
                )

        return str_

    def get_transition_symmetry(self, vector, point_group_rep):
        # determines symmetry of specific transition
        # code replicated from WESTpy

        fcivec = self.transform_transition_to_fci(vector)

        # get <S^2> and multiplicity for state
        ss, ms = self.get_spin(vector)
        # generate best-guess integer multiplicity
        ms = int(np.rint(ms))

        if not self.spin_flip:
            nelec_ = self.n_elec
        else:
            nelec_ = (self.n_elec[0] - 1, self.n_elec[1] + 1)

        h_ = point_group_rep.point_group.h
        ctable_ = point_group_rep.point_group.ctable

        irprojs = []
        irreps = []

        for irrep, chis in ctable_.items():
            l = chis[0]
            pfcivec = np.zeros_like(fcivec)

            for chi, U in zip(chis, point_group_rep.rep_matrices.values()):
                pfcivec += chi * transform_ci_for_orbital_rotation(
                    ci=fcivec, norb=self.n_orbitals, nelec=nelec_, u=U.T
                )

            irprojs.append(l / h_ * np.sum(fcivec * pfcivec))
            irreps.append(irrep)

        # find maximal symmetry
        imax = np.argmax(irprojs)
        # symm = f"{irreps[imax]}({irprojs[imax]:.2f})"

        return str(ms) + str(irreps[imax])
