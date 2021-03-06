import math
try:
    import signatory
except ImportError:
    signatory = None
import torch

from . import _impl


class CppDiscrepancy(torch.nn.Module):
    """Discrepancy functions can either be coded in Python or C++.

    If they're done in C++ then they can be parallelised over, whereas if they are done in Python then the GIL implies
    that there's some serialisation.

    In order to facilitate this, C++ discrepancy functions should be subclasses of this class. They should have the
    C++ function as a 'fn' attribute, and precisely one Tensor, that they get to control, as an 'arg' attribute.
    """
    # Every instance of a subclass must have two attributes available:
    # A function 'fn' with signature (Tensor, Tensor, Tensor, Tensor) -> Tensor
    # An 'arg', which is a Tensor.

    def forward(self, time, path1, path2):
        # We never actually call this forward method as part of the shapelet transform, but it's here in case people
        # want to try calling this outside of the shapelet transform.
        return self.fn(time, path1, path2, self.arg)


class L2Discrepancy(CppDiscrepancy):
    """Computes the L2 discrepancy between two paths."""
    fn = _impl.l2_discrepancy

    def __init__(self, in_channels, pseudometric=True, metric_type='general'):
        """
        Called with some path `f` and some shapelet `g` such that
        ```
        f, g \colon [0, T] \to R^in_channels,
        ```
        which are described by as being the unique continuous piecewise linear functions such that
        ```
        f(times[i]) == path1[i] for all i,
        g(times[i]) == path2[i] for all i,
        ```
        where `times` is a strictly increasing 1D tensor of shape (length,) for some  value `length`, and `path1` is a
        tensor of shape (..., length, in_channels) and `path2` is a tensor of shape (length, in_channels). [So yes,
        `path2` has no batch dimensions.]

        Then this  computes
        ```
        sqrt( \int_{times[0]}^{times[-1]} || A(f(t) - g(t)) ||_2^2 dt )
        ```
        where ||.||_2 denotes the L^2 vector norm, and A is a matrix of shape (l, l), which:
            - will be the identity matrix if pseudometric==False
            - will be learnt and diagonal if pseudometric=True and metric_type == 'diagonal'
            - will be learnt and square if pseudometric==True and metric_type == 'general'.

        The return value will be a tensor of shape (...).

        Arguments:
            in_channels: The number of input channels of the path.
            pseudometric: Whether to take a learnt linear transformation beforehand. Defaults to True.
            metric_type: Either 'general' or 'diagonal'. Whether to take a general learnt linear transformation or just
                a diagonal one. Defaults to 'general'.
        """
        super(L2Discrepancy, self).__init__()

        assert metric_type in ('general', 'diagonal'), "Valid values for 'metric_type' are 'general' and 'diagonal'."

        self.in_channels = in_channels
        self.pseudometric = pseudometric
        self.metric_type = metric_type

        if pseudometric:
            if metric_type == 'general':
                linear = torch.empty(in_channels, in_channels, requires_grad=True)
                torch.nn.init.kaiming_uniform_(linear, a=math.sqrt(5))
            else:
                linear = torch.empty(in_channels, requires_grad=True)
                torch.nn.init.uniform_(linear, 0.9, 1.1)
            self.arg = torch.nn.Parameter(linear)
        else:
            self.arg = torch.nn.Parameter(torch.empty(()))

    def extra_repr(self):
        return "in_channels={}, pseudometric={}".format(self.in_channels, self.pseudometric)


class LogsignatureDiscrepancy(torch.nn.Module):
    """Calculates the p-logsignature distance between two paths."""
    def __init__(self, in_channels, depth, p=2, include_time=True, pseudometric=True, metric_type='general'):
        """
        Called with some path `f` and some shapelet `g` such that
        ```
        f, g \colon [0, T] \to R^in_channels,
        ```
        which are described by as being the unique continuous piecewise linear functions such that
        ```
        f(times[i]) == path1[i] for all i,
        g(times[i]) == path2[i] for all i,
        ```
        where `times` is a strictly increasing 1D tensor of shape (length,) for some  value `length`, and `path1` is a
        tensor of shape (..., length, in_channels) and `path2` is a tensor of shape (*, length, in_channels), where
        '...' and '*' represent potentially different batch dimensions.

        Then let `q = logsig(f, depth) - logsig(g, depth)` be the difference in their logsignatures to depth `depth`,
        which will be a vector of size `l = logsignature_channels(in_channels, depth)`.

        Then this discrepancy calculates
        ```
        ||Aq||_p
        ```
        where ||.||_p denotes the L^p vector norm, and A is a matrix of shape (l, l), which:
            - will be the identity matrix if pseudometric==False
            - will be learnt and diagonal if pseudometric=True and metric_type == 'diagonal'
            - will be learnt and square if pseudometric==True and metric_type == 'general'.

        The return value will be a tensor of shape (..., *).

        Arguments:
            in_channels: The number of input channels of the path.
            depth: An integer describing the depth of the logsignature transform to take.
            p: A number in [1, \infty] specifying the parameter p of the distance. Defaults to 2.
            include_time: Boolean. Whether to take the logsignature discrepancy of the time-augmented path or not.
                Defaults to True. (Setting this to False produces a pseudometric rather similar in spirit to dynamic
                time warping, in that it's reparameterisation invariant.)
            pseudometric: Whether to take a learnt linear transformation beforehand. Defaults to True.
            metric_type: Either 'general' or 'diagonal'. Whether to take a general learnt linear transformation or just
                a diagonal one. Defaults to 'general'.
        """
        super(LogsignatureDiscrepancy, self).__init__()

        assert metric_type in ('general', 'diagonal'), "Valid values for 'metric_type' are 'general' and 'diagonal'."
        if signatory is None:
            raise ImportError("Signatory must be installed to compute logsignature discrepancies. It can be found at "
                              "`https://github.com/patrick-kidger/signatory`. See also the installation instructions "
                              "for `torchshapelets` at "
                              "`https://github.com/jambo6/generalised_shapelets/tree/master/torchshapelets`. ")

        self.in_channels = in_channels
        self.depth = depth
        self.p = p
        self.include_time = include_time
        self.pseudometric = pseudometric
        self.metric_type = metric_type

        if pseudometric:
            channels = in_channels
            if include_time:
                channels += 1
            logsignature_channels = signatory.logsignature_channels(channels, depth)
            if metric_type == 'general':
                linear = torch.randn(logsignature_channels, logsignature_channels, requires_grad=True)
                torch.nn.init.kaiming_uniform_(linear, a=math.sqrt(5))
            else:
                linear = torch.randn(logsignature_channels, requires_grad=True)
                torch.nn.init.uniform_(linear, 0.9, 1.1)
            self.linear = torch.nn.Parameter(linear)
        else:
            self.register_parameter('linear', None)

        self.logsignature = signatory.Logsignature(depth=depth)

    def extra_repr(self):
        return "in_channels={}, depth={}, p={}, include_time={}, pseudometric={}, pseudometric_type={}" \
               "".format(self.in_channels,
                         self.depth,
                         self.p,
                         self.include_time,
                         self.pseudometric,
                         self.metric_type)
        
    def forward(self, times, path1, path2):
        # times has shape (length,)
        # path1 has shape (..., length, channels)
        # path2 has shape (*, length, channels)

        path1_batch_dims = path1.shape[:-2]
        path2_batch_dims = path2.shape[:-2]

        if self.include_time:
            # append time to both paths
            time_channel1 = time_channel2 = times.unsqueeze(-1)
            for dim in path1_batch_dims:
                time_channel1 = time_channel1.unsqueeze(0).expand(dim, *time_channel1.shape)
            for dim in path2_batch_dims:
                time_channel2 = time_channel2.unsqueeze(0).expand(dim, *time_channel2.shape)
            path1 = torch.cat([time_channel1, path1], dim=-1)
            path2 = torch.cat([time_channel2, path2], dim=-1)

        # Create a single batch dimension for compatibility with Signatory
        path1 = path1.view(-1, path1.size(-2), path1.size(-1))
        path2 = path2.view(-1, path2.size(-2), path2.size(-1))

        logsignature1 = self.logsignature(path1)
        logsignature2 = self.logsignature(path2)

        logsignature1 = logsignature1.view(*path1_batch_dims, logsignature1.size(-1))
        logsignature2 = logsignature2.view(*path2_batch_dims, logsignature2.size(-1))

        for _ in path1_batch_dims:
            logsignature2.unsqueeze_(0)
        for _ in path2_batch_dims:
            logsignature1.unsqueeze_(-2)
        logsignature1 = logsignature1.expand(*path1_batch_dims, *path2_batch_dims, logsignature1.size(-1))
        logsignature2 = logsignature2.expand(*path1_batch_dims, *path2_batch_dims, logsignature1.size(-1))

        logsignature_diff = logsignature1 - logsignature2

        if self.pseudometric:
            if self.metric_type == 'general':
                logsignature_diff = logsignature_diff @ self.linear
            else:
                logsignature_diff = logsignature_diff * self.linear
        return logsignature_diff.norm(p=self.p, dim=-1)
