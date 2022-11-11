"""Classes for calculating neutron spectra using the
'sampler' and 'relscatt' modules.
"""

import numpy as np
from scipy.interpolate import interp1d, RectBivariateSpline

from dress import relkin
from dress import relscatt
from dress import sampler
from dress import tokapart


phi_hat = np.array([0,1.0,0]).reshape(3,1)    # toroidal basis vector


# Class for holding reactant info and samples
# ----------------------------------------------

class Reactant:
    
    def __init__(self, particle, n_samples=0, B_dir=[0,1,0]):
        
        self.particle = particle
        self.B_dir = B_dir

        # Initialize without MC sample
        self.P = None
        self.n_samples = int(n_samples)

    def __repr__(self):
        return 'Reactant: {}'.format(self.particle.long_name)

    @property
    def m(self):
        return self.particle.m

    @property
    def B_dir(self):
        return self._B_dir

    @B_dir.setter
    def B_dir(self, B):
        self._B_dir = np.array(B, 'd')

    # Handling the sample vectors
    @property
    def v(self):
        return self._v

    @v.setter
    def v(self, v_):
        if v_.shape != (3,self.n_samples):
            raise ValueError('Wrong shape of v (wrong number of samples?)')
        else:
            self._v = v_
            self.P = relkin.get_four_momentum(v_, self.m)

    def set_energy_pitch(self, E, p):
        self.E = E
        self.pitch = p
        
        self.v = tokapart.add_gyration(E, p, self.m, self.B_dir)


    # Convenience functions for sampling various distributions

    def sample_maxwellian_dist(self, T, pitch_range=[-1,1], v_rot=0.0):
        """ Sample reactant four-momenta from a Maxwellian distribution with a given temperature 
        (with uniform pitch distribution in a given range). Units in keV. 

        A toroidal rotation speed (including sign) can also be supplied (m/s)."""

        m = self.m
    
        # The (kinetic) energy is distributed as a chi2 variable with 3 degrees of freedom
        E = np.random.chisquare(3, size=self.n_samples) * 0.5 * T

        # Sample pitch values
        pitch = sampler.sample_uniform(pitch_range, self.n_samples)

        # Store results
        self.set_energy_pitch(E, pitch)
    
        # Add rotation
        if np.any(np.abs(v_rot)) > 0.0:
            v_rot = v_rot * phi_hat          # toroidal rotation [m/s]
            self.v = self.v + v_rot

    def sample_mono_dist(self, E0, pitch_range=[-1,1]):
        """ Sample four-momenta of reactant particles ('a' or 'b') with a mono-energetic
        distribution (with uniform pitch distribution in a given range).
        Units in keV. """
    
        # Sample energies
        E = sampler.sample_mono(E0, self.n_samples)

        # Sample pitch values
        pitch = sampler.sample_uniform(pitch_range, self.n_samples)

        # Store results
        self.set_energy_pitch(E, pitch)

    def sample_E_dist(self, Ep, fp, pitch_range=[-1,1], quiet=True, method='acc_rej'):
        """ Sample four-momenta of reactant particles ('a' or 'b') with a tabulated
        energy distribution fp given at the points Ep (with uniform pitch distribution 
        in a given range). Units in keV. """
    
        if method == 'acc_rej':
            # Function to sample from
            f = interp1d(Ep, fp, bounds_error=False, fill_value=0)
            
            # Sampling space
            lims = ([Ep[0]], [Ep[-1]])
            fmax = fp.max()
            
            # Sample energies
            s = sampler.sample_acc_rej(f, lims, fmax, self.n_samples, quiet=quiet)
            E = s[:,0]
            
        elif method == 'inv_trans':
            E = sampler.sample_inv_trans(fp, Ep, self.n_samples)

        else:
            raise ValueError(f'Unknown sampling method: {method}')
        
        # Sample pitch values
        pitch = sampler.sample_uniform(pitch_range, self.n_samples)

        # Store results
        self.set_energy_pitch(E, pitch)

    def sample_EP_dist(self, Ep, pitch_p, fp, quiet=True):
        """ Sample four-momenta of reactant particles ('a' or 'b') with a tabulated
        (E,pitch) distribution fp given at the points (Ep, pitch_p). Units in keV. """
    
        # Function to sample from
        rbs = RectBivariateSpline(Ep, pitch_p, fp)

        def f(x,y): return rbs(x, y, grid=False)

        # Sampling space
        lims = ([Ep[0], pitch_p[0]], [Ep[-1], pitch_p[-1]])
        fmax = fp.max()

        # Sample energy and pitch
        s = sampler.sample_acc_rej(f, lims, fmax, self.n_samples, quiet=quiet)
        E = s[:,0]
        pitch = s[:,1]

        # Store results
        self.set_energy_pitch(E, pitch)
        

# Calculation of spectrum from sampled four-momenta.
# -----------------------------------------------------

class SpectrumCalculator:
    """ 
    Calculate product spectrum from reactions between particles with
    four-momenta 'Pa' and 'Pb'. 'u' is the product emission direction 
    (if None, each event gets a random direction).
    """

    def __init__(self, reaction, B_dir=[0,1,0], n_samples=1e6):

        self._B_dir = np.array(B_dir, 'd')
        self._n_samples = int(n_samples)
        self.reaction = reaction
        self.weights = None

        # 4*pi emission by default
        self.u = None

    def __repr__(self):
        return f'Spectrum calculator for the reaction {self.reaction.formula}'

    @property
    def reaction(self):
        return self._reaction

    @reaction.setter
    def reaction(self, r):
        
        self._reaction = r

        self.reactant_a = r.a
        self.reactant_b = r.b
        self.product_1 = r.p1
        self.product_2 = r.p2
        self.product_3 = r.p3

    @property
    def reactant_a(self):
        return self._reactant_a

    @reactant_a.setter
    def reactant_a(self, particle):
        self._reactant_a = Reactant(particle, n_samples=self.n_samples, B_dir=self.B_dir)

    @property
    def reactant_b(self):
        return self._reactant_b

    @reactant_b.setter
    def reactant_b(self, particle):
        self._reactant_b = Reactant(particle, n_samples=self.n_samples, B_dir=self.B_dir)

    @property
    def ma(self):
        return self.reactant_a.m

    @property
    def mb(self):
        return self.reactant_b.m

    @property
    def m1(self):
        return self.product_1.m

    @property
    def m2(self):
        return self.product_2.m

    @property
    def m3(self):
        if self.product_3 is None:
            return None
        else:
            return self.product_3.m

    @property
    def B_dir(self):
        return self._B_dir

    @B_dir.setter
    def B_dir(self, B):

        self._B_dir = np.array(B, 'd')
            
        self.reactant_a.B_dir = B
        self.reactant_b.B_dir = B
    
    @property
    def n_samples(self):
        return self._n_samples

    @n_samples.setter
    def n_samples(self, n):
        n = int(n)
        self._n_samples = n

        self.reactant_a.n_samples = n
        self.reactant_b.n_samples = n

    @property
    def weights(self):
        if self._weights is None:
            return np.ones(self.n_samples)/self.n_samples
        else:
            return self._weights

    @weights.setter
    def weights(self, w):
        self._weights = w

    def __call__(self, bins=None, bin_width=25.0, normalize=False, which_product=1):
        """
        Compute reactant spectrum. The units of the spectrum depends on the 
        units of the 'weights' attribute. The 'normalize' keyword
        can be used to normalize the spectrum to unit sum.
    
        If 'bins' is given it is passed as a keyword argument to np.histogram. 
        If bins=None (default), the bins will be constructed so as to cover the full 
        range of calculated product energies.
        
        The bin width of the spectrum histogram can be specified with 'bin_width' (keV). 
        (only effective if bins=None).
        
        Additionally, both the 'bins' and the 'bin_width' attributes can be length-2 lists,
        in which case the spectrum is resolved both in energy and cos(theta), where
        theta is the angle between the B-field and the emission direction.
        """        
        
        # Calculate relevant kinematic data of the reactants
        Pa = self.reactant_a.P
        Pb = self.reactant_b.P

        reactant_data = relscatt.ReactantData(Pa, Pb, self.ma, self.mb)

        # Emission directions
        if self.u is None:
            u = sampler.sample_sphere(self.n_samples)   # random emission directions
        else:
            u = np.array(self.u)
            if u.ndim == 1:
                u = np.array(u).reshape(3,1)   # same emission direction for all particles            

        # Setup for computing the spectrum of the requested product
        m, mr, mr2 = self._get_product_masses(which_product)

        # Compute product four-momenta
        if self.product_3 is not None:             
            P = relscatt.three_body_event(reactant_data, m, mr, mr2, u)
        else:
            P = relscatt.two_body_event(reactant_data, m, mr, u)

        # Compute reactivity
        sigmav = relscatt.get_reactivity(reactant_data, P, self.reaction)
    
        # Make attributes with reactivity for possible later use
        self.sigmav = sigmav

        # Bin all events
        weights_tot = self.weights * sigmav
        
        result = self._make_spec_hist(P, m, bins, bin_width, weights_tot, normalize)
        
        return result

    def _get_product_masses(self, which_product):
        """Return the masses to be used in the calls to relscatt."""
        if which_product == 1:
            m = self.m1
            mr = self.m2
            mr2 = self.m3
        elif which_product == 2:
            m = self.m2
            mr = self.m1
            mr2 = self.m3
        elif which_product == 3:
            if self.m3 is not None:
                m = self.m3
                mr = self.m1
                mr2 = self.m2
            else:
                raise ValueError('Invalid product choice (there are only two reaction products)')
        else:
            raise ValueError('Invalid product choice')

        return m, mr, mr2

    def _make_spec_hist(self, P, m, bins, bin_width, weights, normalize):

        E = P[0] - m           # kinetic energy (keV)
        valid = ~np.isnan(E)   # do not try to bin forbidden events
        E = E[valid]
        P = P[:,valid]
        weights = weights[valid]

        # Make attributes with product momenta and kinetic energies,
        # for possible later use
        self.P_prod = P
        self.E_prod = E

        # How to bin events
        if bins is None:
    
            return_bins = True

            if type(bin_width) == list:
                # Set up for computing 2D spectrum with default energy and pitch range
                bins_E = np.arange(E.min()-5*bin_width[0], E.max()+6*bin_width[0], bin_width[0])
                bins_A = np.arange(-1, 1+bin_width[1], bin_width[1])

                bins = [bins_E, bins_A]

            else:
                # Set up for computing energy spectrum with default bins
                bins = np.arange(E.min()-5*bin_width, E.max()+6*bin_width, bin_width)

        else:
            return_bins = False

        # Bin in 1D or 2D
        if type(bins) == list:
            # Bin in both energy and emission direction
            A = np.dot(P[1:].T, self.B_dir)
            p = np.linalg.norm(P[1:], ord=2, axis=0)
            b = np.linalg.norm(self.B_dir, ord=2, axis=0)
            A = A / (p*b)      # cosine of emission angles w.r.t. B-field

            spec = np.histogram2d(E, A, bins=bins, weights=weights)[0]
        else:
            spec = np.histogram(E, bins=bins, weights=weights)[0]

        # Possibly normalize to unit sum
        if normalize:
            spec = spec / spec.sum()

        # Return results
        if return_bins:

            if spec.ndim == 2:
                # Return spectrum and bin edges of the 2D histogram
                return spec, bins[0], bins[1]

            else:
                # Return spectrum and bin centers of the 1D histogram
                E_axis = 0.5*(bins[1:] + bins[:-1])
                return spec, E_axis

        else:
            # Return only the spectrum, since the bins were supplied as input
            return spec
        

