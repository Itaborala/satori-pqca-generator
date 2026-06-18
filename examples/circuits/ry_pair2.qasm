OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
ry(pi/4) q[0];
cry(pi/4) q[0], q[1];
